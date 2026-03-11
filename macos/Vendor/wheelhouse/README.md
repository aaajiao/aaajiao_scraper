Place prebuilt wheels for the macOS importer runtime here.

`prepare_seed.sh` installs runtime dependencies from this directory with `pip --no-index`.
If the directory is empty, the build falls back to an existing local `macos/Vendor/python_runtime`
and refuses to download packages from the network.
