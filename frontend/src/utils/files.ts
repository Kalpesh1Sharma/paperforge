export const readableSize = (bytes: number) => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
export const validPdf = (file: File) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
