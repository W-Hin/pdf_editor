export const TOOL_CONFIGS = {
  merge: {
    title: "Merge PDF",
    category: "Organize",
    multiFile: true,
    mode: "view",
    preview: "merge",
    endpoint: "merge",
    filenameSuffix: "_merged",
    fields: [{ name: "filename", label: "Output filename", type: "text", default: "" }],
  },
  split: {
    title: "Split PDF",
    category: "Organize",
    multiFile: false,
    mode: "view",
    preview: "split",
    endpoint: "split",
    fields: [
      { name: "pages_per_file", label: "Pages per output file", type: "number", default: 1, min: 1 },
    ],
  },
  "remove-pages": {
    title: "Remove pages",
    category: "Organize",
    multiFile: false,
    mode: "select",
    endpoint: "remove-pages",
    fields: [],
  },
  "extract-pages": {
    title: "Extract pages",
    category: "Organize",
    multiFile: false,
    mode: "select",
    endpoint: "extract-pages",
    fields: [],
  },
  "reorder-pages": {
    title: "Reorder pages",
    category: "Organize",
    multiFile: false,
    mode: "reorder",
    endpoint: "reorder-pages",
    fields: [],
  },
  rotate: {
    title: "Rotate PDF",
    category: "Edit",
    multiFile: false,
    mode: "view",
    preview: "rotate",
    endpoint: "rotate",
    fields: [
      { name: "angle", label: "Rotate by", type: "select", options: [90, 180, 270], default: 90 },
    ],
  },
  watermark: {
    title: "Add watermark",
    category: "Edit",
    multiFile: false,
    mode: "view",
    preview: "watermark",
    endpoint: "watermark",
    fields: [
      { name: "text", label: "Watermark text", type: "text", default: "" },
      {
        name: "opacity",
        label: "Opacity (%)",
        type: "range",
        min: 10,
        max: 100,
        default: 30,
        scale: 0.01,
      },
    ],
  },
  "add-page-numbers": {
    title: "Add page numbers",
    category: "Edit",
    multiFile: false,
    mode: "view",
    preview: "page-numbers",
    endpoint: "add-page-numbers",
    fields: [
      {
        name: "position",
        label: "Position",
        type: "select",
        options: [
          { value: "bottom-center", label: "Bottom center" },
          { value: "bottom-right", label: "Bottom right" },
          { value: "bottom-left", label: "Bottom left" },
          { value: "top-center", label: "Top center" },
          { value: "top-right", label: "Top right" },
          { value: "top-left", label: "Top left" },
        ],
        default: "bottom-center",
      },
      {
        name: "format",
        label: "Format",
        type: "select",
        options: [
          { value: "number", label: "3" },
          { value: "number-of-total", label: "3 / 12" },
          { value: "page-x-of-y", label: "Page 3 of 12" },
        ],
        default: "number",
      },
    ],
  },
  crop: {
    title: "Crop PDF",
    category: "Edit",
    multiFile: false,
    mode: "view",
    preview: "crop",
    endpoint: "crop",
    fields: [],
  },
  compress: {
    title: "Compress PDF",
    category: "Optimize",
    multiFile: false,
    mode: "view",
    // Compression only re-encodes embedded images — it doesn't change how
    // a page looks, so there's nothing meaningful to show visually. The
    // page grid still renders (as input context); this note explains why
    // it looks identical before and after.
    previewNote: "Compression changes file size, not appearance — pages will look the same.",
    endpoint: "compress",
    fields: [
      { name: "image_quality", label: "Image quality", type: "range", min: 10, max: 100, default: 60 },
    ],
  },
  "to-images": {
    title: "PDF to Image",
    category: "Convert",
    multiFile: false,
    mode: "view",
    endpoint: "to-images",
    fields: [
      { name: "image_format", label: "Format", type: "select", options: ["jpg", "png"], default: "jpg" },
    ],
  },
  "to-word": {
    title: "PDF to Word",
    category: "Convert",
    multiFile: false,
    mode: "view",
    // A real preview would mean actually running the conversion — Word's
    // layout engine doesn't render in a browser, so there's no cheap way
    // to show this before committing. See the file's own note in the app.
    previewNote: "Word documents can't be previewed here — conversion quality depends on the PDF's layout.",
    endpoint: "to-word",
    fields: [],
  },
};
