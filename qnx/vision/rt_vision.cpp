// rt_vision — all camera-touching code for Praxis (QNX, C++).
//
// Modes:
//   rt_vision preview --out BMP
//       Grab one settled frame -> BMP. Used for the live camera view in the UI
//       (the dashboard polls this a couple of times a second).
//   rt_vision stream --out BMP
//       Keep one viewfinder open and atomically refresh a preview BMP until the
//       process is terminated. This avoids repeatedly reopening the QNX camera.
//   rt_vision score --out FILE [--endbmp BMP] [--slice N]
//       Grab ONE settled post-task frame that contains BOTH the printed BLUE
//       reference pattern and the participant's RED pen trace. Walk the image in
//       vertical slices `N` px wide; in each slice take the centroid-y of the
//       blue pixels and of the red pixels; per-slice error = |y_red - y_blue| px.
//       No corner markers, no homography — pure pixel geometry from one image.
//       Writes FILE (JSON: black/red centroid polylines + per-slice deviations
//       + summary) and, optionally, an end-state BMP.
//
// Frames are NV12 from the QNX Sensor Framework camera API (libcamapi).
// Red/black detection is done directly on the Y/UV planes — no OpenCV needed.
#include <camera/camera_api.h>

#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <signal.h>
#include <string>
#include <vector>
#include <sys/stat.h>
#include <unistd.h>

// ---------------------------------------------------------------- utilities
static int64_t mono_ns() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

// ------------------------------------------------------------- frame buffer
// The viewfinder callback copies the newest frame here; processing happens on
// the main thread so the callback stays fast.
struct FrameStore {
  std::mutex m;
  std::vector<uint8_t> data;   // full NV12 buffer copy
  uint32_t w = 0, h = 0, stride = 0, uv_offset = 0, uv_stride = 0;
  int64_t t = 0;
  uint64_t seq = 0;
};
static FrameStore g_frame;
static std::atomic<uint64_t> g_frames_seen{0};
static std::atomic<bool> g_running{true};

static void stop_signal(int) { g_running.store(false); }

static void viewfinder_cb(camera_handle_t, camera_buffer_t* buf, void*) {
  if (!buf || buf->frametype != CAMERA_FRAMETYPE_NV12) return;
  const camera_frame_nv12_t& d = buf->framedesc.nv12;
  // NV12: Y plane (h rows of stride) + interleaved UV (h/2 rows of uv_stride)
  size_t need = (size_t)d.uv_offset + (size_t)(d.height / 2) * d.uv_stride;
  std::lock_guard<std::mutex> lk(g_frame.m);
  if (g_frame.data.size() < need) g_frame.data.resize(need);
  memcpy(g_frame.data.data(), buf->framebuf, need);
  g_frame.w = d.width;
  g_frame.h = d.height;
  g_frame.stride = d.stride;
  g_frame.uv_offset = d.uv_offset;
  g_frame.uv_stride = d.uv_stride;
  g_frame.t = mono_ns();
  g_frame.seq = ++g_frames_seen;
}

// Snapshot of the shared frame for processing.
struct Frame {
  std::vector<uint8_t> data;
  uint32_t w = 0, h = 0, stride = 0, uv_offset = 0, uv_stride = 0;
  int64_t t = 0;
  uint64_t seq = 0;

  inline uint8_t Y(int x, int y) const { return data[(size_t)y * stride + x]; }
  inline void UV(int x, int y, uint8_t& u, uint8_t& v) const {
    size_t o = uv_offset + (size_t)(y / 2) * uv_stride + (size_t)(x / 2) * 2;
    u = data[o];
    v = data[o + 1];
  }
};

static bool take_frame(Frame& f, uint64_t newer_than) {
  std::lock_guard<std::mutex> lk(g_frame.m);
  if (g_frame.seq == 0 || g_frame.seq <= newer_than) return false;
  f.data = g_frame.data;
  f.w = g_frame.w; f.h = g_frame.h; f.stride = g_frame.stride;
  f.uv_offset = g_frame.uv_offset; f.uv_stride = g_frame.uv_stride;
  f.t = g_frame.t; f.seq = g_frame.seq;
  return true;
}

// ------------------------------------------------------------------ camera
static camera_handle_t g_cam = CAMERA_HANDLE_INVALID;

static bool camera_start() {
  camera_error_t err = camera_open(CAMERA_UNIT_1, CAMERA_MODE_RO, &g_cam);
  if (err != CAMERA_EOK) {
    fprintf(stderr, "camera_open failed: %d\n", err);
    return false;
  }
  // Ask for NV12; if the property set fails we proceed with defaults and the
  // callback filters on frametype anyway.
  err = camera_set_vf_property(g_cam, CAMERA_IMGPROP_FORMAT,
                               CAMERA_FRAMETYPE_NV12);
  if (err != CAMERA_EOK)
    fprintf(stderr, "warn: set NV12 property returned %d (using defaults)\n", err);
  err = camera_start_viewfinder(g_cam, viewfinder_cb, nullptr, nullptr);
  if (err != CAMERA_EOK) {
    fprintf(stderr, "camera_start_viewfinder failed: %d\n", err);
    camera_close(g_cam);
    return false;
  }
  return true;
}

static void camera_stop() {
  if (g_cam != CAMERA_HANDLE_INVALID) {
    camera_stop_viewfinder(g_cam);
    camera_close(g_cam);
    g_cam = CAMERA_HANDLE_INVALID;
  }
}

static int wait_first_frame(int timeout_ms) {
  int waited = 0;
  while (g_frames_seen.load() == 0 && waited < timeout_ms) {
    usleep(50 * 1000);
    waited += 50;
  }
  return g_frames_seen.load() > 0;
}

// Open camera, let exposure settle, grab one frame, close. Returns false on any
// failure (message already printed to stderr).
static bool grab_settled(Frame& f, int settle_ms) {
  if (!camera_start()) return false;
  if (!wait_first_frame(5000)) {
    fprintf(stderr, "no frames from camera within 5s\n");
    camera_stop();
    return false;
  }
  usleep(settle_ms * 1000);
  bool ok = take_frame(f, 0);
  camera_stop();
  return ok;
}

// --------------------------------------------------------------- detection
// Reference line = BLUE, attempt = RED. In YUV these sit in opposite chroma
// corners (red: Cr high / Cb low; blue: Cb high / Cr low), so they never bleed
// into each other and blue is not confused with shadows/paper the way a dark
// "black" threshold was.
struct Thresh {
  int red_v_min = 150;    // Cr high => red ink
  int red_u_max = 128;    // Cb <= mid => warm (red)
  int red_y_min = 60;     // red ink is bright enough to be ink, not shadow
  int blue_u_min = 140;   // Cb high => blue ink (loosened for shadowed blue)
  int blue_v_max = 125;   // Cr low  => blue (excludes magenta/purple leaning red)
  int blue_y_min = 30;    // exclude near-black sensor noise
  // Purple scale marker: high Cb AND high Cr (the fourth chroma corner). Paper
  // is near-neutral and never has BOTH channels high, so purple stays clear of
  // the washed-out paper. Cb>=145 keeps it clear of red-over-blue overlap (whose
  // Cb~130), so Cr/Y can be loose enough to catch the whole bar incl. its
  // less-saturated / shadowed end.
  int purple_u_min = 145;  // Cb high (the discriminating channel)
  int purple_v_min = 133;  // Cr high (loosened: bar ends dip to ~136)
  int purple_y_min = 18;   // catch the shadowed end of the bar
};

static bool is_red(const Frame& f, int x, int y, const Thresh& th) {
  uint8_t u, v;
  f.UV(x, y, u, v);
  return v >= th.red_v_min && u <= th.red_u_max && f.Y(x, y) >= th.red_y_min;
}

static bool is_blue(const Frame& f, int x, int y, const Thresh& th) {
  uint8_t u, v;
  f.UV(x, y, u, v);
  return u >= th.blue_u_min && v <= th.blue_v_max && f.Y(x, y) >= th.blue_y_min;
}

static bool is_purple(const Frame& f, int x, int y, const Thresh& th) {
  uint8_t u, v;
  f.UV(x, y, u, v);
  return u >= th.purple_u_min && v >= th.purple_v_min && f.Y(x, y) >= th.purple_y_min;
}

// -------------------------------------------------------------- BMP output
// Write the frame to a 24-bit BMP, decimated by `dec` in both axes (dec=1 =>
// full resolution). Decimation keeps the live-preview payload small.
static bool write_bmp_dec(const std::string& path, const Frame& f, int dec) {
  if (dec < 1) dec = 1;
  int w = (int)f.w / dec, h = (int)f.h / dec;
  int rowsz = (w * 3 + 3) & ~3;
  uint32_t datasz = rowsz * h, filesz = 54 + datasz;
  std::vector<uint8_t> row(rowsz, 0);
  FILE* fp = fopen(path.c_str(), "wb");
  if (!fp) return false;
  uint8_t hd[54] = {'B', 'M'};
  auto put32 = [&](int off, uint32_t v) { memcpy(hd + off, &v, 4); };
  auto put16 = [&](int off, uint16_t v) { memcpy(hd + off, &v, 2); };
  put32(2, filesz); put32(10, 54); put32(14, 40);
  put32(18, (uint32_t)w); put32(22, (uint32_t)h);
  put16(26, 1); put16(28, 24);
  put32(34, datasz);
  fwrite(hd, 1, 54, fp);
  auto cl = [](double d) { return (uint8_t)(d < 0 ? 0 : d > 255 ? 255 : d); };
  for (int oy = h - 1; oy >= 0; --oy) {  // BMP is bottom-up
    int y = oy * dec;
    for (int ox = 0; ox < w; ++ox) {
      int x = ox * dec;
      uint8_t u, v;
      f.UV(x, y, u, v);
      double Y = f.Y(x, y), U = u - 128.0, V = v - 128.0;
      row[ox * 3 + 0] = cl(Y + 1.772 * U);             // B
      row[ox * 3 + 1] = cl(Y - 0.344 * U - 0.714 * V); // G
      row[ox * 3 + 2] = cl(Y + 1.402 * V);             // R
    }
    fwrite(row.data(), 1, rowsz, fp);
  }
  fclose(fp);
  return true;
}

static bool write_bmp(const std::string& path, const Frame& f) {
  int w = f.w, h = f.h;
  int rowsz = (w * 3 + 3) & ~3;
  uint32_t datasz = rowsz * h, filesz = 54 + datasz;
  std::vector<uint8_t> row(rowsz, 0);
  FILE* fp = fopen(path.c_str(), "wb");
  if (!fp) return false;
  uint8_t hd[54] = {'B', 'M'};
  auto put32 = [&](int off, uint32_t v) { memcpy(hd + off, &v, 4); };
  auto put16 = [&](int off, uint16_t v) { memcpy(hd + off, &v, 2); };
  put32(2, filesz); put32(10, 54); put32(14, 40);
  put32(18, (uint32_t)w); put32(22, (uint32_t)h);
  put16(26, 1); put16(28, 24);
  put32(34, datasz);
  fwrite(hd, 1, 54, fp);
  for (int y = h - 1; y >= 0; --y) {  // BMP is bottom-up
    for (int x = 0; x < w; ++x) {
      uint8_t u, v;
      f.UV(x, y, u, v);
      double Y = f.Y(x, y), U = u - 128.0, V = v - 128.0;
      auto cl = [](double d) { return (uint8_t)(d < 0 ? 0 : d > 255 ? 255 : d); };
      row[x * 3 + 0] = cl(Y + 1.772 * U);             // B
      row[x * 3 + 1] = cl(Y - 0.344 * U - 0.714 * V); // G
      row[x * 3 + 2] = cl(Y + 1.402 * V);             // R
    }
    fwrite(row.data(), 1, rowsz, fp);
  }
  fclose(fp);
  return true;
}

// ------------------------------------------------------------------- score
// Vertical-slice accuracy: for a LEFT->RIGHT pattern (single-valued in x), the
// blue reference and red trace each reduce to one centroid per column-slice.
struct Args {
  std::string mode, out, endbmp;
  int slice_px = 16;   // vertical-slice width in pixels
  double scale_mm = 0; // known length of the green scale bar (mm); 0 = disabled
  Thresh th;
};

// Measure the purple scale bar's pixel length. Coarse-grid connected
// components; pick the most bar-like blob (long + thin) so any stray purple is
// ignored. Returns length in px (0 if none), sets out_px to purple pixel count.
static double measure_scale_bar(const Frame& f, const Thresh& th, int& out_px,
                                double bar_ends[4]) {
  const int cell = 16;
  int gw = (f.w + cell - 1) / cell, gh = (f.h + cell - 1) / cell;
  std::vector<int> cnt((size_t)gw * gh, 0);
  int total = 0;
  for (int y = 0; y < (int)f.h; y += 2)
    for (int x = 0; x < (int)f.w; x += 2)
      if (is_purple(f, x, y, th)) { cnt[(size_t)(y / cell) * gw + (x / cell)]++; ++total; }
  out_px = total;
  bar_ends[0] = bar_ends[1] = bar_ends[2] = bar_ends[3] = 0;

  std::vector<char> lab((size_t)gw * gh, 0);
  std::vector<size_t> stack;
  double best_len = 0;
  int bmnx = 0, bmny = 0, bmxx = 0, bmxy = 0;  // best blob bbox (cells)
  for (int gy = 0; gy < gh; ++gy) {
    for (int gx = 0; gx < gw; ++gx) {
      size_t idx = (size_t)gy * gw + gx;
      if (cnt[idx] < 2 || lab[idx]) continue;
      int minx = gx, maxx = gx, miny = gy, maxy = gy;
      lab[idx] = 1;
      stack.push_back(idx);
      while (!stack.empty()) {
        size_t c = stack.back(); stack.pop_back();
        int cy = (int)(c / gw), cx = (int)(c % gw);
        if (cx < minx) minx = cx; if (cx > maxx) maxx = cx;
        if (cy < miny) miny = cy; if (cy > maxy) maxy = cy;
        for (int dy = -1; dy <= 1; ++dy)
          for (int dx = -1; dx <= 1; ++dx) {
            int nx = cx + dx, ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
            size_t n = (size_t)ny * gw + nx;
            if (cnt[n] >= 2 && !lab[n]) { lab[n] = 1; stack.push_back(n); }
          }
      }
      double dxp = (maxx - minx + 1) * cell, dyp = (maxy - miny + 1) * cell;
      double len = dxp > dyp ? dxp : dyp, thick = dxp > dyp ? dyp : dxp;
      double aspect = len / (thick > 0 ? thick : 1);
      if (aspect >= 3.0 && len > best_len) {  // bar-like only
        best_len = len;
        bmnx = minx; bmny = miny; bmxx = maxx; bmxy = maxy;
      }
    }
  }
  if (best_len > 0) {  // endpoints along the bar's long axis (image pixels)
    double x0 = bmnx * cell, x1 = (bmxx + 1) * cell;
    double y0 = bmny * cell, y1 = (bmxy + 1) * cell;
    if ((x1 - x0) >= (y1 - y0)) {  // horizontal bar
      double ym = (y0 + y1) / 2;
      bar_ends[0] = x0; bar_ends[1] = ym; bar_ends[2] = x1; bar_ends[3] = ym;
    } else {                       // vertical bar
      double xm = (x0 + x1) / 2;
      bar_ends[0] = xm; bar_ends[1] = y0; bar_ends[2] = xm; bar_ends[3] = y1;
    }
  }
  return best_len;
}

static int do_score(const Args& a) {
  Frame f;
  if (!grab_settled(f, 700)) return 2;
  const int W = (int)f.w, H = (int)f.h;
  const int step = a.slice_px > 0 ? a.slice_px : 16;
  const int nslices = (W + step - 1) / step;
  const int MIN_HITS = 3;  // subsampled pixels needed to trust a slice's colour

  std::vector<double> bsx(nslices, 0), bsy(nslices, 0);  // blue reference sums
  std::vector<double> rsx(nslices, 0), rsy(nslices, 0);  // red attempt sums
  std::vector<int> bn(nslices, 0), rn(nslices, 0);

  // blue reference and red attempt live in opposite chroma corners — check
  // blue first, they don't overlap. Subsample by 2 in both axes for speed.
  for (int x = 0; x < W; x += 2) {
    int s = x / step;
    for (int y = 0; y < H; y += 2) {
      if (is_blue(f, x, y, a.th)) { bn[s]++; bsx[s] += x; bsy[s] += y; }
      else if (is_red(f, x, y, a.th)) { rn[s]++; rsx[s] += x; rsy[s] += y; }
    }
  }

  // px -> mm from the purple scale bar (bar-shaped blob).
  double px_per_mm = 0;
  bool have_scale = false;
  int gn = 0;
  double bar_ends[4] = {0, 0, 0, 0};
  if (a.scale_mm > 0) {
    double len_px = measure_scale_bar(f, a.th, gn, bar_ends);
    if (len_px > 5) { px_per_mm = len_px / a.scale_mm; have_scale = true; }
  }

  // Per-slice centroids -> polylines + deviations where both colours present.
  std::vector<double> bpx, bpy, rpx, rpy, dev;
  int n_ref = 0, n_scored = 0;
  double sum_dev = 0, sum_dev2 = 0, max_dev = 0;
  double bymin = 1e18, bymax = -1e18;
  for (int s = 0; s < nslices; ++s) {
    bool hasB = bn[s] >= MIN_HITS, hasR = rn[s] >= MIN_HITS;
    double by = 0, ry = 0;
    if (hasB) {
      by = bsy[s] / bn[s];
      bpx.push_back(bsx[s] / bn[s]); bpy.push_back(by);
      ++n_ref;
      if (by < bymin) bymin = by;
      if (by > bymax) bymax = by;
    }
    if (hasR) {
      ry = rsy[s] / rn[s];
      rpx.push_back(rsx[s] / rn[s]); rpy.push_back(ry);
    }
    if (hasB && hasR) {
      double d = std::fabs(ry - by);
      dev.push_back(d);
      sum_dev += d; sum_dev2 += d * d;
      if (d > max_dev) max_dev = d;
      ++n_scored;
    }
  }

  double mean_dev = n_scored ? sum_dev / n_scored : 0.0;
  double rms_dev = n_scored ? std::sqrt(sum_dev2 / n_scored) : 0.0;
  double coverage = n_ref ? 100.0 * n_scored / n_ref : 0.0;
  double extent = (bymax > bymin) ? (bymax - bymin) : 0.0;

  if (!a.endbmp.empty()) write_bmp(a.endbmp, f);

  FILE* fp = fopen(a.out.c_str(), "w");
  if (!fp) { fprintf(stderr, "cannot open %s\n", a.out.c_str()); return 2; }
  fprintf(fp, "{\"ok\":%s,\"frame\":[%d,%d],\"slice_px\":%d,",
          n_scored >= 3 ? "true" : "false", W, H, step);
  fprintf(fp, "\"n_ref_slices\":%d,\"n_scored_slices\":%d,", n_ref, n_scored);
  fprintf(fp, "\"coverage_pct\":%.1f,\"mean_dev_px\":%.2f,\"max_dev_px\":%.2f,"
              "\"rms_dev_px\":%.2f,\"ref_extent_px\":%.1f,",
          coverage, mean_dev, max_dev, rms_dev, extent);
  // Scale + millimetre conversions (null when no green bar is detected).
  if (have_scale) {
    fprintf(fp, "\"scale_px_per_mm\":%.4f,\"scale_px\":%d,"
                "\"mean_dev_mm\":%.2f,\"max_dev_mm\":%.2f,\"rms_dev_mm\":%.2f,"
                "\"ref_extent_mm\":%.2f,",
            px_per_mm, gn, mean_dev / px_per_mm, max_dev / px_per_mm,
            rms_dev / px_per_mm, extent / px_per_mm);
  } else {
    fprintf(fp, "\"scale_px_per_mm\":null,\"scale_px\":%d,"
                "\"mean_dev_mm\":null,\"max_dev_mm\":null,\"rms_dev_mm\":null,"
                "\"ref_extent_mm\":null,",
            gn);
  }
  auto put_poly = [&](const char* name, const std::vector<double>& xs,
                      const std::vector<double>& ys) {
    fprintf(fp, "\"%s\":[", name);
    for (size_t i = 0; i < xs.size(); ++i)
      fprintf(fp, "%s[%.1f,%.1f]", i ? "," : "", xs[i], ys[i]);
    fprintf(fp, "]");
  };
  put_poly("reference", bpx, bpy); fprintf(fp, ",");
  put_poly("red", rpx, rpy); fprintf(fp, ",");
  if (have_scale)
    fprintf(fp, "\"scale_bar\":[[%.1f,%.1f],[%.1f,%.1f]],", bar_ends[0],
            bar_ends[1], bar_ends[2], bar_ends[3]);
  else
    fprintf(fp, "\"scale_bar\":null,");
  fprintf(fp, "\"dev\":[");
  for (size_t i = 0; i < dev.size(); ++i) fprintf(fp, "%s%.1f", i ? "," : "", dev[i]);
  fprintf(fp, "]}\n");
  fclose(fp);

  // machine-readable summary line on stdout for the server
  printf("{\"ok\":%s,\"n_scored_slices\":%d,\"mean_dev_px\":%.2f,\"frame\":[%d,%d]}\n",
         n_scored >= 3 ? "true" : "false", n_scored, mean_dev, W, H);
  return n_scored >= 3 ? 0 : 3;
}

static int do_preview(const Args& a) {
  Frame f;
  if (!grab_settled(f, 250)) return 2;
  std::string out = a.out.empty() ? std::string("/tmp/preview.bmp") : a.out;
  // decimate to ~640px wide so the live view stays light over the hotspot
  int dec = (int)f.w / 640;
  if (dec < 1) dec = 1;
  if (!write_bmp_dec(out, f, dec)) { fprintf(stderr, "cannot write %s\n", out.c_str()); return 2; }
  printf("{\"ok\":true,\"frame\":[%u,%u],\"file\":\"%s\"}\n", f.w, f.h, out.c_str());
  return 0;
}

static int do_stream(const Args& a) {
  std::string out = a.out.empty() ? std::string("/tmp/preview.bmp") : a.out;
  std::string temp = out + ".tmp";
  signal(SIGTERM, stop_signal);
  signal(SIGINT, stop_signal);
  if (!camera_start()) return 2;
  if (!wait_first_frame(5000)) {
    fprintf(stderr, "no frames from camera within 5s\n");
    camera_stop();
    return 2;
  }
  usleep(250 * 1000);
  uint64_t last_seq = 0;
  int published = 0;
  while (g_running.load()) {
    Frame f;
    if (take_frame(f, last_seq)) {
      last_seq = f.seq;
      int dec = (int)f.w / 480;
      if (dec < 1) dec = 1;
      if (write_bmp_dec(temp, f, dec) && rename(temp.c_str(), out.c_str()) == 0)
        ++published;
    }
    usleep(100 * 1000);
  }
  camera_stop();
  unlink(temp.c_str());
  printf("{\"ok\":true,\"frames_published\":%d,\"file\":\"%s\"}\n",
         published, out.c_str());
  return 0;
}

static int do_capture(const Args& a) {
  Frame f;
  if (!grab_settled(f, 700)) return 2;
  std::string out = a.out.empty() ? std::string("/tmp/capture.bmp") : a.out;
  if (!write_bmp_dec(out, f, 1)) { fprintf(stderr, "cannot write %s\n", out.c_str()); return 2; }
  printf("{\"ok\":true,\"frame\":[%u,%u],\"file\":\"%s\"}\n",
         f.w, f.h, out.c_str());
  return 0;
}

// -------------------------------------------------------------------- main
int main(int argc, char** argv) {
  Args a;
  if (argc < 2) {
    fprintf(stderr,
            "usage: rt_vision preview --out BMP\n"
            "         one settled frame -> BMP (live camera view)\n"
            "       rt_vision stream --out BMP\n"
            "         continuously refresh BMP using one open viewfinder\n"
            "       rt_vision capture --out BMP\n"
            "         one settled full-resolution frame -> BMP\n"
            "       rt_vision score --out FILE [--endbmp BMP] [--slice N]\n"
            "         one frame -> vertical-slice black-vs-red deviation score\n");
    return 1;
  }
  a.mode = argv[1];
  for (int i = 2; i < argc; ++i) {
    std::string s = argv[i];
    auto next = [&]() { return (i + 1 < argc) ? std::string(argv[++i]) : std::string(); };
    if (s == "--out") a.out = next();
    else if (s == "--endbmp") a.endbmp = next();
    else if (s == "--slice") a.slice_px = atoi(next().c_str());
    else if (s == "--scale-mm") a.scale_mm = atof(next().c_str());
    else if (s == "--red-v") a.th.red_v_min = atoi(next().c_str());
    else if (s == "--blue-u") a.th.blue_u_min = atoi(next().c_str());
    else if (s == "--blue-v") a.th.blue_v_max = atoi(next().c_str());
    else if (s == "--purple-u") a.th.purple_u_min = atoi(next().c_str());
    else if (s == "--purple-v") a.th.purple_v_min = atoi(next().c_str());
  }
  if (a.mode == "preview") return do_preview(a);
  if (a.mode == "stream") return do_stream(a);
  if (a.mode == "capture") return do_capture(a);
  if (a.mode == "score") return do_score(a);
  fprintf(stderr, "unknown mode '%s'\n", a.mode.c_str());
  return 1;
}
