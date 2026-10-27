from localocr.postprocess import dispatch

if __name__ == "__main__":
    dispatch()
    from localocr.gui.app import main

    raise SystemExit(main())
