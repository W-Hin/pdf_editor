// Shared file-type helpers. The app accepts PDFs plus these image formats
// (Images to PDF), so several components need to tell them apart to pick an
// icon or a preview strategy.
export const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png"];

export function isImageFilename(filename) {
  const lower = filename.toLowerCase();
  return IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}
