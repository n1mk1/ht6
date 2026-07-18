// rt_vision — all camera-touching code for RehabTrace (QNX, C++).
//
// Modes:
//   rt_vision calibrate --out DIR
//       Grab one clean frame of the mat (no hands!). Detect 4 red corner
//       crosses -> homography (pixels -> mat millimetres). Extract the black
//       reference line as an ordered mm polyline. Writes:
//         DIR/calib.json  DIR/reference.json  DIR/snapshot.bmp
//   rt_vision track --calib DIR --out FILE [--max-frames N] [--stopfile F] [--endbmp F]
//       Stream frames; per frame find the red pen tip (ignoring regions near
//       the corner crosses), map to mm, append a JSON line to FILE:
//         {"t":<mono_ns>,"valid":true,"x":..,"y":..,"px":..}
//       Stops when stopfile appears or max-frames reached. Optionally writes
//       an end-state BMP of the last frame.
//
// Frames are NV12 from the QNX Sensor Framework camera API (libcamapi).
// Red/black detection is done directly on Y/UV planes — no OpenCV needed.
#include <camera/camera_api.h>

#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

// ---------------------------------------------------------------- utilities
static int64_t mono_ns() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

struct P2 { double x = 0, y = 0; };

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

// --------------------------------------------------------------- detection
struct Thresh {
  int red_v_min = 150;    // Cr high => red/orange ink
  int red_u_max = 128;    // Cb <= mid => warm (red/orange)
  int red_y_min = 60;     // ink is brighter than the dark reference
  int black_y_max = 110;  // dark reference line / crosses (warm lighting)
  int chroma_tol = 40;    // dark marker under warm light isn't perfectly grey
};

static bool is_red(const Frame& f, int x, int y, const Thresh& th) {
  uint8_t u, v;
  f.UV(x, y, u, v);
  return v >= th.red_v_min && u <= th.red_u_max && f.Y(x, y) >= th.red_y_min;
}

static bool is_black(const Frame& f, int x, int y, const Thresh& th) {
  if (f.Y(x, y) > th.black_y_max) return false;
  uint8_t u, v;
  f.UV(x, y, u, v);
  return std::abs((int)u - 128) <= th.chroma_tol &&
         std::abs((int)v - 128) <= th.chroma_tol;
}

// Cluster red pixels into blobs using a coarse grid + flood fill.
struct Blob { double cx = 0, cy = 0; int n = 0; };

static std::vector<Blob> find_red_blobs(const Frame& f, const Thresh& th,
                                        const std::vector<P2>& exclude,
                                        double excl_r) {
  const int step = 2, cell = 16;
  int gw = (f.w + cell - 1) / cell, gh = (f.h + cell - 1) / cell;
  std::vector<int> cnt((size_t)gw * gh, 0);
  std::vector<double> sx((size_t)gw * gh, 0), sy((size_t)gw * gh, 0);

  for (int y = 0; y < (int)f.h; y += step) {
    for (int x = 0; x < (int)f.w; x += step) {
      if (!is_red(f, x, y, th)) continue;
      bool skip = false;
      for (const auto& e : exclude) {
        double dx = x - e.x, dy = y - e.y;
        if (dx * dx + dy * dy < excl_r * excl_r) { skip = true; break; }
      }
      if (skip) continue;
      size_t g = (size_t)(y / cell) * gw + (x / cell);
      cnt[g]++; sx[g] += x; sy[g] += y;
    }
  }
  // Flood-fill occupied grid cells into blobs (8-connected).
  std::vector<int> label((size_t)gw * gh, -1);
  std::vector<Blob> blobs;
  std::vector<size_t> stack;
  for (int gy = 0; gy < gh; ++gy) {
    for (int gx = 0; gx < gw; ++gx) {
      size_t g = (size_t)gy * gw + gx;
      if (cnt[g] == 0 || label[g] != -1) continue;
      int id = (int)blobs.size();
      blobs.push_back({});
      stack.push_back(g);
      label[g] = id;
      while (!stack.empty()) {
        size_t c = stack.back(); stack.pop_back();
        int cy2 = (int)(c / gw), cx2 = (int)(c % gw);
        blobs[id].n += cnt[c];
        blobs[id].cx += sx[c];
        blobs[id].cy += sy[c];
        for (int dy = -1; dy <= 1; ++dy)
          for (int dx = -1; dx <= 1; ++dx) {
            int nx = cx2 + dx, ny = cy2 + dy;
            if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
            size_t n = (size_t)ny * gw + nx;
            if (cnt[n] > 0 && label[n] == -1) { label[n] = id; stack.push_back(n); }
          }
      }
    }
  }
  for (auto& b : blobs) {
    if (b.n > 0) { b.cx /= b.n; b.cy /= b.n; }
  }
  // biggest first
  for (size_t i = 0; i < blobs.size(); ++i)
    for (size_t j = i + 1; j < blobs.size(); ++j)
      if (blobs[j].n > blobs[i].n) std::swap(blobs[i], blobs[j]);
  return blobs;
}

// Auto-detect 4 BLACK corner crosses: centroid of dark pixels in each image
// corner window (the reference design lives in the middle, away from corners).
static bool find_corner_crosses(const Frame& f, const Thresh& th, P2 out[4]) {
  double wx = f.w * 0.33, wy = f.h * 0.33;
  double regs[4][4] = {
      {0, 0, wx, wy},                                    // TL
      {(double)f.w - wx, 0, (double)f.w, wy},            // TR
      {(double)f.w - wx, (double)f.h - wy, (double)f.w, (double)f.h},  // BR
      {0, (double)f.h - wy, wx, (double)f.h},            // BL
  };
  for (int r = 0; r < 4; ++r) {
    double sx = 0, sy = 0;
    int n = 0;
    for (int y = (int)regs[r][1]; y < (int)regs[r][3]; y += 2)
      for (int x = (int)regs[r][0]; x < (int)regs[r][2]; x += 2)
        if (is_black(f, x, y, th)) { sx += x; sy += y; ++n; }
    if (n < 15) return false;
    out[r] = {sx / n, sy / n};
  }
  return true;
}

// ------------------------------------------------------------- homography
// Solve img(x,y) -> mat(X,Y) from 4 correspondences (DLT, h8=1).
struct Homography {
  double h[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
  bool valid = false;
  P2 map(P2 p) const {
    double w = h[6] * p.x + h[7] * p.y + h[8];
    if (std::fabs(w) < 1e-12) w = 1e-12;
    return {(h[0] * p.x + h[1] * p.y + h[2]) / w,
            (h[3] * p.x + h[4] * p.y + h[5]) / w};
  }
};

static Homography solve_homography(const P2 img[4], const P2 mat[4]) {
  double A[8][9] = {};
  for (int i = 0; i < 4; ++i) {
    double x = img[i].x, y = img[i].y, X = mat[i].x, Y = mat[i].y;
    double* r1 = A[2 * i];
    double* r2 = A[2 * i + 1];
    r1[0] = x; r1[1] = y; r1[2] = 1; r1[6] = -X * x; r1[7] = -X * y; r1[8] = X;
    r2[3] = x; r2[4] = y; r2[5] = 1; r2[6] = -Y * x; r2[7] = -Y * y; r2[8] = Y;
  }
  // Gaussian elimination with partial pivoting on the 8x9 system.
  Homography H;
  for (int c = 0; c < 8; ++c) {
    int piv = c;
    for (int r = c + 1; r < 8; ++r)
      if (std::fabs(A[r][c]) > std::fabs(A[piv][c])) piv = r;
    if (std::fabs(A[piv][c]) < 1e-9) return H;  // singular -> invalid
    if (piv != c)
      for (int k = 0; k < 9; ++k) std::swap(A[piv][k], A[c][k]);
    for (int r = 0; r < 8; ++r) {
      if (r == c) continue;
      double f = A[r][c] / A[c][c];
      for (int k = c; k < 9; ++k) A[r][k] -= f * A[c][k];
    }
  }
  for (int i = 0; i < 8; ++i) H.h[i] = A[i][8] / A[i][i];
  H.h[8] = 1.0;
  H.valid = true;
  return H;
}

// -------------------------------------------------------------- BMP output
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
      row[x * 3 + 0] = cl(Y + 1.772 * U);            // B
      row[x * 3 + 1] = cl(Y - 0.344 * U - 0.714 * V); // G
      row[x * 3 + 2] = cl(Y + 1.402 * V);            // R
    }
    fwrite(row.data(), 1, rowsz, fp);
  }
  fclose(fp);
  return true;
}

// ------------------------------------------------- reference line -> polyline
// Collect black pixels, map to mm, quantize to a grid, then order by greedy
// nearest-neighbour walk from an endpoint.
static std::vector<P2> extract_polyline(const Frame& f, const Homography& H,
                                        const Thresh& th, const P2 cross_mm[4],
                                        double mat_w, double mat_h,
                                        bool want_red = false) {
  const double grid = 2.0;  // mm quantization
  std::vector<P2> pts;
  {
    // dedupe via sorted key set
    std::vector<int64_t> keys;
    for (int y = 0; y < (int)f.h; y += 2) {
      for (int x = 0; x < (int)f.w; x += 2) {
        bool hit = want_red ? is_red(f, x, y, th) : is_black(f, x, y, th);
        if (!hit) continue;
        P2 mm = H.map({(double)x, (double)y});
        if (mm.x < 0 || mm.y < 0 || mm.x > mat_w || mm.y > mat_h) continue;
        bool near_cross = false;
        for (int i = 0; i < 4; ++i) {
          double dx = mm.x - cross_mm[i].x, dy = mm.y - cross_mm[i].y;
          if (dx * dx + dy * dy < 14.0 * 14.0) { near_cross = true; break; }
        }
        if (near_cross) continue;
        int gx = (int)(mm.x / grid), gy = (int)(mm.y / grid);
        int64_t key = (int64_t)gy * 100000 + gx;
        bool seen = false;
        for (int64_t k : keys)
          if (k == key) { seen = true; break; }
        if (!seen) {
          keys.push_back(key);
          pts.push_back({(gx + 0.5) * grid, (gy + 0.5) * grid});
        }
      }
    }
  }
  if (pts.size() < 3) return pts;

  // endpoint = point with the fewest neighbours within 2*grid
  auto ncount = [&](size_t i) {
    int n = 0;
    for (size_t j = 0; j < pts.size(); ++j) {
      if (j == i) continue;
      double dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y;
      if (dx * dx + dy * dy <= (2 * grid) * (2 * grid)) ++n;
    }
    return n;
  };
  size_t start = 0;
  int best = 1 << 30;
  for (size_t i = 0; i < pts.size(); ++i) {
    int n = ncount(i);
    if (n < best) { best = n; start = i; }
  }
  // greedy walk
  std::vector<char> used(pts.size(), 0);
  std::vector<P2> ordered;
  size_t cur = start;
  used[cur] = 1;
  ordered.push_back(pts[cur]);
  const double max_jump2 = (grid * 4) * (grid * 4);
  while (true) {
    double bd = 1e18;
    size_t bi = pts.size();
    for (size_t j = 0; j < pts.size(); ++j) {
      if (used[j]) continue;
      double dx = pts[j].x - pts[cur].x, dy = pts[j].y - pts[cur].y;
      double d = dx * dx + dy * dy;
      if (d < bd) { bd = d; bi = j; }
    }
    if (bi == pts.size() || bd > max_jump2) break;
    used[bi] = 1;
    ordered.push_back(pts[bi]);
    cur = bi;
  }
  return ordered;
}

// -------------------------------------------------------------- json helpers
static std::string jnum(double v) {
  char b[32];
  snprintf(b, sizeof b, "%.2f", v);
  return b;
}

// ------------------------------------------------------------------- modes
struct Args {
  std::string mode, out, calib, stopfile, endbmp;
  int max_frames = 0;
  // cross centre positions on the mat, mm (TL,TR,BR,BL). Default: letter
  // paper, crosses 15mm in from each edge. Override with --corners.
  P2 cross_mm[4] = {{15, 15}, {200.9, 15}, {200.9, 264.4}, {15, 264.4}};
  double mat_w = 215.9, mat_h = 279.4;
  bool have_corners_px = false;      // manual clicked corners (image pixels)
  P2 corners_px[4];                  // TL,TR,BR,BL
  Thresh th;
};

static int wait_first_frame(int timeout_ms) {
  int waited = 0;
  while (g_frames_seen.load() == 0 && waited < timeout_ms) {
    usleep(50 * 1000);
    waited += 50;
  }
  return g_frames_seen.load() > 0;
}

static int do_calibrate(const Args& a) {
  if (!camera_start()) return 2;
  if (!wait_first_frame(5000)) {
    fprintf(stderr, "no frames from camera within 5s\n");
    camera_stop();
    return 2;
  }
  // let exposure settle, then take the 10th-ish frame
  usleep(700 * 1000);
  Frame f;
  if (!take_frame(f, 0)) { camera_stop(); return 2; }
  camera_stop();

  fprintf(stderr, "frame %ux%u stride=%u\n", f.w, f.h, f.stride);

  // Always save the snapshot first so the mat/lighting can be inspected even
  // when detection fails.
  ::mkdir(a.out.c_str(), 0755);
  write_bmp(a.out + "/snapshot.bmp", f);

  // Corner source: manual clicked pixels (TL,TR,BR,BL) or auto black-cross.
  P2 img[4];
  if (a.have_corners_px) {
    for (int i = 0; i < 4; ++i) img[i] = a.corners_px[i];
  } else if (!find_corner_crosses(f, a.th, img)) {
    fprintf(stderr, "auto corner detection failed — click the 4 corners\n");
    printf("{\"ok\":false,\"error\":\"corners_not_found\"}\n");
    return 3;
  }
  Homography H = solve_homography(img, a.cross_mm);
  if (!H.valid) {
    printf("{\"ok\":false,\"error\":\"homography_singular\"}\n");
    return 3;
  }
  std::vector<P2> ref = extract_polyline(f, H, a.th, a.cross_mm, a.mat_w, a.mat_h);

  ::mkdir(a.out.c_str(), 0755);
  write_bmp(a.out + "/snapshot.bmp", f);

  FILE* fp = fopen((a.out + "/calib.json").c_str(), "w");
  if (!fp) return 2;
  fprintf(fp, "{\"H\":[");
  for (int i = 0; i < 9; ++i) fprintf(fp, "%s%.10g", i ? "," : "", H.h[i]);
  fprintf(fp, "],\"corners_img\":[");
  for (int i = 0; i < 4; ++i)
    fprintf(fp, "%s[%.1f,%.1f]", i ? "," : "", img[i].x, img[i].y);
  fprintf(fp, "],\"corners_mm\":[");
  for (int i = 0; i < 4; ++i)
    fprintf(fp, "%s[%.1f,%.1f]", i ? "," : "", a.cross_mm[i].x, a.cross_mm[i].y);
  fprintf(fp, "],\"frame\":[%u,%u]}\n", f.w, f.h);
  fclose(fp);

  fp = fopen((a.out + "/reference.json").c_str(), "w");
  if (!fp) return 2;
  fprintf(fp, "{\"points_mm\":[");
  for (size_t i = 0; i < ref.size(); ++i)
    fprintf(fp, "%s[%s,%s]", i ? "," : "", jnum(ref[i].x).c_str(),
            jnum(ref[i].y).c_str());
  fprintf(fp, "]}\n");
  fclose(fp);

  printf("{\"ok\":true,\"corners\":4,\"ref_points\":%zu,\"frame\":[%u,%u]}\n",
         ref.size(), f.w, f.h);
  return 0;
}

static int do_track(const Args& a) {
  // load corner image positions from calib.json (cheap parse: read numbers)
  std::vector<P2> corner_img;
  Homography H;
  {
    FILE* fp = fopen((a.calib + "/calib.json").c_str(), "r");
    if (!fp) {
      fprintf(stderr, "cannot open %s/calib.json\n", a.calib.c_str());
      return 2;
    }
    char buf[4096];
    size_t n = fread(buf, 1, sizeof buf - 1, fp);
    buf[n] = 0;
    fclose(fp);
    // parse "H":[ ... 9 numbers ... ] and "corners_img":[[x,y]x4]
    const char* p = strstr(buf, "\"H\":[");
    if (!p) return 2;
    p += 5;
    for (int i = 0; i < 9; ++i) {
      H.h[i] = strtod(p, (char**)&p);
      while (*p == ',' || *p == ' ') ++p;
    }
    H.valid = true;
    p = strstr(buf, "\"corners_img\":[");
    if (!p) return 2;
    p += 15;
    for (int i = 0; i < 4; ++i) {
      while (*p && *p != '[') ++p;
      if (*p) ++p;
      double x = strtod(p, (char**)&p);
      while (*p == ',' || *p == ' ') ++p;
      double y = strtod(p, (char**)&p);
      corner_img.push_back({x, y});
      while (*p && *p != ']') ++p;
      if (*p) ++p;
    }
  }

  FILE* out = fopen(a.out.c_str(), "w");
  if (!out) {
    fprintf(stderr, "cannot open out file %s\n", a.out.c_str());
    return 2;
  }
  if (!camera_start()) return 2;
  if (!wait_first_frame(5000)) {
    fprintf(stderr, "no frames\n");
    camera_stop();
    return 2;
  }

  uint64_t last_seq = 0;
  int frames = 0;
  Frame f;
  while (true) {
    if (!a.stopfile.empty() && access(a.stopfile.c_str(), F_OK) == 0) break;
    if (a.max_frames > 0 && frames >= a.max_frames) break;
    if (!take_frame(f, last_seq)) { usleep(5 * 1000); continue; }
    last_seq = f.seq;
    ++frames;

    auto blobs = find_red_blobs(f, a.th, corner_img, 45.0);
    if (!blobs.empty() && blobs[0].n >= 6) {
      P2 mm = H.map({blobs[0].cx, blobs[0].cy});
      fprintf(out, "{\"t\":%lld,\"valid\":true,\"x\":%s,\"y\":%s,\"px\":%d}\n",
              (long long)f.t, jnum(mm.x).c_str(), jnum(mm.y).c_str(), blobs[0].n);
    } else {
      fprintf(out, "{\"t\":%lld,\"valid\":false}\n", (long long)f.t);
    }
    fflush(out);
  }
  if (!a.endbmp.empty() && f.seq) write_bmp(a.endbmp, f);
  camera_stop();
  fclose(out);
  fprintf(stderr, "tracked %d frames\n", frames);
  return 0;
}

// ------------------------------------------------------ capture (post-task)
static bool load_homography(const std::string& calib, Homography& H) {
  FILE* fp = fopen((calib + "/calib.json").c_str(), "r");
  if (!fp) return false;
  char buf[4096];
  size_t n = fread(buf, 1, sizeof buf - 1, fp);
  buf[n] = 0;
  fclose(fp);
  const char* p = strstr(buf, "\"H\":[");
  if (!p) return false;
  p += 5;
  for (int i = 0; i < 9; ++i) {
    H.h[i] = strtod(p, (char**)&p);
    while (*p == ',' || *p == ' ') ++p;
  }
  H.valid = true;
  return true;
}

// Grab ONE settled frame after the task; extract the RED attempt line as an
// ordered mm polyline (corner crosses masked). Writes attempt.json + BMP.
static int do_capture(const Args& a) {
  Homography H;
  if (!load_homography(a.calib, H)) {
    fprintf(stderr, "cannot load %s/calib.json\n", a.calib.c_str());
    return 2;
  }
  if (!camera_start()) return 2;
  if (!wait_first_frame(5000)) {
    fprintf(stderr, "no frames from camera\n");
    camera_stop();
    return 2;
  }
  usleep(700 * 1000);  // let exposure settle
  Frame f;
  if (!take_frame(f, 0)) { camera_stop(); return 2; }
  camera_stop();

  std::vector<P2> att =
      extract_polyline(f, H, a.th, a.cross_mm, a.mat_w, a.mat_h, /*want_red=*/true);

  if (!a.endbmp.empty()) write_bmp(a.endbmp, f);
  FILE* fp = fopen(a.out.c_str(), "w");
  if (!fp) return 2;
  fprintf(fp, "{\"points_mm\":[");
  for (size_t i = 0; i < att.size(); ++i)
    fprintf(fp, "%s[%s,%s]", i ? "," : "", jnum(att[i].x).c_str(),
            jnum(att[i].y).c_str());
  fprintf(fp, "]}\n");
  fclose(fp);
  printf("{\"ok\":%s,\"attempt_points\":%zu}\n",
         att.size() >= 3 ? "true" : "false", att.size());
  return att.size() >= 3 ? 0 : 3;
}

// -------------------------------------------------------------------- main
int main(int argc, char** argv) {
  Args a;
  if (argc < 2) {
    fprintf(stderr,
            "usage: rt_vision calibrate --out DIR [--corners x,y,x,y,x,y,x,y]\n"
            "         clean mat -> corners, homography, BLACK reference line\n"
            "       rt_vision capture --calib DIR --out FILE --endbmp BMP\n"
            "         post-task photo -> RED attempt line (mm polyline)\n"
            "       rt_vision track --calib DIR --out FILE [--max-frames N]\n"
            "                       [--stopfile F] [--endbmp F]  (live debug)\n");
    return 1;
  }
  a.mode = argv[1];
  for (int i = 2; i < argc; ++i) {
    std::string s = argv[i];
    auto next = [&]() { return (i + 1 < argc) ? std::string(argv[++i]) : std::string(); };
    if (s == "--out") a.out = next();
    else if (s == "--calib") a.calib = next();
    else if (s == "--stopfile") a.stopfile = next();
    else if (s == "--endbmp") a.endbmp = next();
    else if (s == "--max-frames") a.max_frames = atoi(next().c_str());
    else if (s == "--corners") {
      std::string v = next();
      const char* p = v.c_str();
      for (int k = 0; k < 4; ++k) {
        a.cross_mm[k].x = strtod(p, (char**)&p); if (*p == ',') ++p;
        a.cross_mm[k].y = strtod(p, (char**)&p); if (*p == ',') ++p;
      }
    }
    else if (s == "--corners-px") {  // image pixels TL,TR,BR,BL from UI clicks
      std::string v = next();
      const char* p = v.c_str();
      for (int k = 0; k < 4; ++k) {
        a.corners_px[k].x = strtod(p, (char**)&p); if (*p == ',') ++p;
        a.corners_px[k].y = strtod(p, (char**)&p); if (*p == ',') ++p;
      }
      a.have_corners_px = true;
    }
    else if (s == "--red-v") a.th.red_v_min = atoi(next().c_str());
    else if (s == "--black-y") a.th.black_y_max = atoi(next().c_str());
  }
  if (a.mode == "preview") {  // grab one frame -> BMP, for aiming the camera
    if (!camera_start()) return 2;
    if (!wait_first_frame(5000)) { camera_stop(); return 2; }
    usleep(500 * 1000);
    Frame f;
    bool ok = take_frame(f, 0);
    camera_stop();
    if (!ok) return 2;
    std::string out = a.out.empty() ? std::string("/tmp/preview.bmp") : a.out;
    write_bmp(out, f);
    printf("{\"ok\":true,\"frame\":[%u,%u],\"file\":\"%s\"}\n", f.w, f.h, out.c_str());
    return 0;
  }
  if (a.mode == "calibrate") return do_calibrate(a);
  if (a.mode == "capture") return do_capture(a);
  if (a.mode == "track") return do_track(a);
  fprintf(stderr, "unknown mode '%s'\n", a.mode.c_str());
  return 1;
}
