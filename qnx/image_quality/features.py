"""Dependency-free feature extraction and inference shared by host and QNX.

The camera emits uncompressed 24-bit BMP files. Reading that format directly
keeps QNX inference independent of Pillow, OpenCV, NumPy, and ML runtimes.
"""
import math
import struct


FEATURE_VERSION = "praxis-bmp-grid-1.0"
GRID_W = 12
GRID_H = 8
SAMPLE_STEP = 8
CHANNELS = 5  # luminance, chroma, red evidence, blue evidence, edge strength
GLOBAL_FEATURES = 7
FEATURE_COUNT = GRID_W * GRID_H * CHANNELS + GLOBAL_FEATURES


def _bmp(path):
    with open(path, "rb") as source:
        data = source.read()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("not_a_bmp")
    offset = struct.unpack_from("<I", data, 10)[0]
    width = struct.unpack_from("<i", data, 18)[0]
    raw_height = struct.unpack_from("<i", data, 22)[0]
    bits = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if width <= 0 or raw_height == 0 or bits != 24 or compression != 0:
        raise ValueError("unsupported_bmp")
    height = abs(raw_height)
    row_size = (width * 3 + 3) & ~3
    if offset + row_size * height > len(data):
        raise ValueError("truncated_bmp")
    return data, offset, width, height, row_size, raw_height > 0


def extract_features(path):
    data, offset, width, height, row_size, bottom_up = _bmp(path)
    sums = [0.0] * (GRID_W * GRID_H * CHANNELS)
    counts = [0] * (GRID_W * GRID_H)
    xs = list(range(0, width, SAMPLE_STEP))
    previous_row = [None] * len(xs)

    n = 0
    y_sum = y2_sum = edge_sum = 0.0
    dark = bright = red_pixels = blue_pixels = 0

    for sample_y, y in enumerate(range(0, height, SAMPLE_STEP)):
        storage_y = height - 1 - y if bottom_up else y
        row = offset + storage_y * row_size
        left_y = None
        for sample_x, x in enumerate(xs):
            pixel = row + x * 3
            b, g, r = data[pixel], data[pixel + 1], data[pixel + 2]
            luminance = (77 * r + 150 * g + 29 * b) / 65280.0
            chroma = (max(r, g, b) - min(r, g, b)) / 255.0
            red = max(0, r - max(g, b)) / 255.0
            blue = max(0, b - max(r, g)) / 255.0

            differences = []
            if left_y is not None:
                differences.append(abs(luminance - left_y))
            if previous_row[sample_x] is not None:
                differences.append(abs(luminance - previous_row[sample_x]))
            edge = sum(differences) / len(differences) if differences else 0.0
            previous_row[sample_x] = luminance
            left_y = luminance

            cell_x = min(GRID_W - 1, x * GRID_W // width)
            cell_y = min(GRID_H - 1, y * GRID_H // height)
            cell = cell_y * GRID_W + cell_x
            base = cell * CHANNELS
            for channel, value in enumerate((luminance, chroma, red, blue, edge)):
                sums[base + channel] += value
            counts[cell] += 1

            n += 1
            y_sum += luminance
            y2_sum += luminance * luminance
            edge_sum += edge
            dark += luminance < 0.20
            bright += luminance > 0.86
            red_pixels += red > 0.08
            blue_pixels += blue > 0.08

    features = []
    for cell, count in enumerate(counts):
        if not count:
            features.extend([0.0] * CHANNELS)
            continue
        base = cell * CHANNELS
        features.extend(sums[base + channel] / count for channel in range(CHANNELS))

    mean_y = y_sum / n
    variance_y = max(0.0, y2_sum / n - mean_y * mean_y)
    features.extend([
        mean_y,
        math.sqrt(variance_y),
        dark / n,
        bright / n,
        red_pixels / n,
        blue_pixels / n,
        edge_sum / n,
    ])
    if len(features) != FEATURE_COUNT:
        raise AssertionError("feature_count_mismatch")
    return features


def mirror_features(features):
    """Mirror grid features horizontally; global features remain unchanged."""
    if len(features) != FEATURE_COUNT:
        raise ValueError("feature_count_mismatch")
    mirrored = [0.0] * (GRID_W * GRID_H * CHANNELS)
    for y in range(GRID_H):
        for x in range(GRID_W):
            source = (y * GRID_W + x) * CHANNELS
            target = (y * GRID_W + (GRID_W - 1 - x)) * CHANNELS
            mirrored[target:target + CHANNELS] = features[source:source + CHANNELS]
    mirrored.extend(features[GRID_W * GRID_H * CHANNELS:])
    return mirrored


def probability(model, features):
    if model.get("feature_version") != FEATURE_VERSION:
        raise ValueError("feature_version_mismatch")
    if len(features) != len(model["weights"]):
        raise ValueError("model_shape_mismatch")
    total = float(model["bias"])
    for value, mean, scale, weight in zip(
            features, model["means"], model["scales"], model["weights"]):
        total += ((value - mean) / scale) * weight
    if total >= 0:
        return 1.0 / (1.0 + math.exp(-total))
    exp_total = math.exp(total)
    return exp_total / (1.0 + exp_total)
