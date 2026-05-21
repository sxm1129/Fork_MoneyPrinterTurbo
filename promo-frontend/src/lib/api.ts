/**
 * Promo API 客户端 — 封装所有后端 API 调用。
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8080/api/v1";

// ────────────────────────── 类型定义 ──────────────────────────

export interface ScriptSegment {
  text: string;
  material_strategy: string;
  matched_user_segment_path: string;
  ai_prompt: string;
  stock_keywords: string[];
}

export interface ScriptVariant {
  variant_id: string;
  style: string;
  full_script: string;
  segments: ScriptSegment[];
  cta_text: string;
  estimated_duration: number;
}

export interface AnalyzedSegment {
  file_path: string;
  segment_type: string;
  start_time: number;
  end_time: number;
  content_tags: string[];
  description: string;
  quality_score: number;
  relevance_score: number;
}

export interface VideoTask {
  video_id: string;
  variant: ScriptVariant;
  voice_name: string;
  state: string;
  progress: number;
  error: string;
  output_path: string;
  thumbnail_path: string;
}

export interface BatchStatus {
  batch_id: string;
  state: string;
  progress: number;
  product_name: string;
  optimized_script: string;
  video_tasks: VideoTask[];
}

export interface ApiResponse<T = any> {
  status: number;
  message: string;
  data: T;
}

// ────────────────────────── 通用请求 ──────────────────────────

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const error = await res.text();
    throw new Error(`API Error ${res.status}: ${error}`);
  }

  const json: ApiResponse<T> = await res.json();
  if (json.status !== 200) {
    throw new Error(json.message || "Unknown API error");
  }

  return json.data;
}

// ────────────────────────── API 函数 ──────────────────────────

/** 1. 上传素材 */
export async function uploadMaterial(file: File) {
  const formData = new FormData();
  formData.append("file", file);

  const url = `${API_BASE}/promo/upload`;
  const res = await fetch(url, {
    method: "POST",
    body: formData,
  });

  const json: ApiResponse<{
    material_id: string;
    filename: string;
    file_path: string;
  }> = await res.json();

  return json.data;
}

/** 2. 分析素材 */
export async function analyzeMaterials(
  materialIds: string[],
  productName: string,
  productDescription: string = ""
) {
  return request<{
    segments: AnalyzedSegment[];
    total: number;
  }>("/promo/analyze", {
    method: "POST",
    body: JSON.stringify({
      material_ids: materialIds,
      product_name: productName,
      product_description: productDescription,
    }),
  });
}

/** 3. 优化口播稿 */
export async function optimizeScript(
  rawScript: string,
  productName: string,
  productDescription: string = "",
  livestreamPurpose: string = "",
  targetLanguage: string = ""
) {
  return request<{ optimized_script: string }>("/promo/optimize-script", {
    method: "POST",
    body: JSON.stringify({
      raw_script: rawScript,
      product_name: productName,
      product_description: productDescription,
      livestream_purpose: livestreamPurpose,
      target_language: targetLanguage,
    }),
  });
}

/** 4. 生成变体 */
export async function generateVariants(
  optimizedScript: string,
  productName: string,
  styles?: string[],
  count: number = 5,
  targetLanguage: string = ""
) {
  return request<{
    variants: ScriptVariant[];
    total: number;
    available_styles: string[];
  }>("/promo/generate-variants", {
    method: "POST",
    body: JSON.stringify({
      optimized_script: optimizedScript,
      product_name: productName,
      styles: styles,
      count,
      target_language: targetLanguage,
    }),
  });
}

/** 4.5. 文案爆款雷达打分诊断 */
export async function diagnoseScript(
  script: string,
  productName: string = ""
) {
  return request<{
    hook_score: number;
    hook_feedback: string;
    conversion_score: number;
    conversion_feedback: string;
    fluency_score: number;
    fluency_feedback: string;
    cta_score: number;
    cta_feedback: string;
  }>("/promo/diagnose", {
    method: "POST",
    body: JSON.stringify({
      script,
      product_name: productName,
    }),
  });
}

/** 5. 提交批量任务 */
export async function createBatch(params: {
  product_name: string;
  raw_script?: string;
  product_description?: string;
  livestream_purpose?: string;
  variants?: any[];
  material_ids?: string[];
  video_aspect?: string;
  voice_names?: string[];
  subtitle_enabled?: boolean;
  max_concurrent?: number;
  motion_intensity?: number;
  cta_config?: { price?: string; original_price?: string; cta_text?: string } | null;
  webhook_url?: string;
}) {
  return request<{ batch_id: string }>("/promo/batch", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

/** 6. 查询批量任务状态 */
export async function getBatchStatus(batchId: string) {
  return request<BatchStatus>(`/promo/batch/${batchId}`);
}

/** 7. 获取所有批量任务 */
export async function listBatches() {
  return request<{ batches: BatchStatus[]; total: number }>("/promo/batches");
}

/** 8. 获取可用风格 */
export async function getStyles() {
  return request<{ styles: string[] }>("/promo/styles");
}

/** 8.5. 分镜段落局部微调 */
export async function updateSegment(
  batchId: string,
  videoId: string,
  index: number,
  segmentData: Partial<ScriptSegment>
) {
  return request<any>(`/promo/batch/${batchId}/videos/${videoId}/segment/${index}/update`, {
    method: "POST",
    body: JSON.stringify({
      new_segment_data: segmentData,
    }),
  });
}

/** 8.6. 极速热合并字幕或BGM */
export async function remuxVideo(
  batchId: string,
  videoId: string,
  remuxData: {
    new_subtitle_content?: string;
    new_bgm_file?: string;
    bgm_volume?: number;
  }
) {
  return request<any>(`/promo/batch/${batchId}/videos/${videoId}/remux`, {
    method: "POST",
    body: JSON.stringify(remuxData),
  });
}

/** 8.7. 获取磁盘空间占用状态 */
export async function getStorageStatus() {
  return request<{
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    used_percent: number;
  }>("/promo/storage-status");
}

/** 9. 获取视频预览 URL */
export function getVideoPreviewUrl(batchId: string, videoId: string) {
  return `${API_BASE}/promo/batch/${batchId}/videos/${videoId}/preview`;
}

/** 10. 获取视频下载 URL */
export function getVideoDownloadUrl(batchId: string, videoId: string) {
  return `${API_BASE}/promo/batch/${batchId}/videos/${videoId}/download`;
}

/** 11. 获取批量 zip 下载 URL */
export function getBatchDownloadUrl(batchId: string) {
  return `${API_BASE}/promo/batch/${batchId}/download`;
}
