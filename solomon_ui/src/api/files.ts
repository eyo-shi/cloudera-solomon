/**
 * TreePane の s3 ルート、および FilePreviewTab 用の hook 群。
 */
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { FilePreviewResponse, S3ListResponse } from "../types";

export interface UploadedFileResult {
  bucket: string;
  key: string;
  name: string;
  size: number;
  s3_uri: string;
}

export async function uploadChatFile(file: File): Promise<UploadedFileResult> {
  const form = new FormData();
  form.append("file", file, file.name);
  const res = await fetch("/api/files/upload", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    let message = `Upload failed: ${res.status}`;
    try {
      const payload = await res.json();
      message =
        payload?.detail?.message ??
        payload?.detail ??
        payload?.message ??
        message;
    } catch {
      /* ignore */
    }
    throw new Error(String(message));
  }
  return res.json() as Promise<UploadedFileResult>;
}

export function useS3Buckets() {
  return useQuery({
    queryKey: ["files", "buckets"],
    queryFn: () =>
      apiFetch<{ buckets: string[] }>("/api/files/buckets").then(
        (res) => res.buckets,
      ),
  });
}

export function useS3List(bucket: string | null, prefix: string) {
  return useQuery({
    queryKey: ["files", "list", bucket, prefix],
    enabled: !!bucket,
    queryFn: () => {
      const params = new URLSearchParams({
        bucket: bucket!,
        prefix,
        delimiter: "/",
      });
      return apiFetch<S3ListResponse>(`/api/files/list?${params.toString()}`);
    },
  });
}

export interface UseFilePreviewArgs {
  bucket: string | null;
  key: string | null;
  sheet?: string;
  rows?: number;
}

export function useFilePreview({
  bucket,
  key,
  sheet,
  rows = 100,
}: UseFilePreviewArgs) {
  return useQuery({
    queryKey: ["files", "preview", bucket, key, sheet, rows],
    enabled: !!bucket && !!key,
    queryFn: () => {
      const params = new URLSearchParams({
        bucket: bucket!,
        key: key!,
        rows: String(rows),
      });
      if (sheet) params.set("sheet", sheet);
      return apiFetch<FilePreviewResponse>(
        `/api/files/preview?${params.toString()}`,
      );
    },
  });
}
