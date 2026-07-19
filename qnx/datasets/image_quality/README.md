# Image-quality dataset

The capture workflow at `http://qnxpi23.local:8080/dataset` collects the
full-resolution camera frames used to train the binary image-quality model.
It labels frames as `valid` or `invalid`; it does not label tracing performance.
Accurate and inaccurate traces are both valid when the image is sharp, clear,
and fully framed.

Captured data is written on the Pi to:

```text
~/steadyeye/datasets/image_quality/data/
  captures/*.bmp
  labels.csv
  manifest.json
  preview.bmp
```

The generated directory is excluded from deployment syncs so `make deploy`
cannot delete collected images. Copy it into the local repository with:

```sh
make pull-dataset
```

`manifest.json` retains the complete 30-shot collection plan and capture state.
`labels.csv` contains only completed captures and is the training input index.
