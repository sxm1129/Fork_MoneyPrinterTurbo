"use client";

import { useEffect, useState, useCallback, Suspense, useRef } from "react";
import { useSearchParams } from "next/navigation";
import {
  getBatchStatus,
  getVideoPreviewUrl,
  getVideoDownloadUrl,
  getBatchDownloadUrl,
  updateSegment,
  remuxVideo,
  getStorageStatus,
  uploadMaterial,
  type BatchStatus,
  type VideoTask,
  type ScriptSegment,
} from "@/lib/api";

const STATE_CONFIG: Record<
  string,
  { color: string; label: string; icon: string }
> = {
  queued: { color: "var(--info)", label: "排队中", icon: "⏳" },
  script_ready: { color: "var(--accent-secondary)", label: "稿件就绪", icon: "📝" },
  tts: { color: "var(--accent-primary)", label: "语音合成", icon: "🔊" },
  material: { color: "var(--warning)", label: "素材获取", icon: "🎬" },
  composing: { color: "var(--accent-primary)", label: "视频合成", icon: "🎥" },
  completed: { color: "var(--success)", label: "已完成", icon: "✅" },
  failed: { color: "var(--danger)", label: "失败", icon: "❌" },
  analyzing: { color: "var(--info)", label: "分析中", icon: "🔍" },
  scripting: { color: "var(--accent-secondary)", label: "文案生成", icon: "📝" },
  generating: { color: "var(--accent-primary)", label: "生成中", icon: "🎬" },
  partial_failed: { color: "var(--warning)", label: "部分失败", icon: "⚠️" },
};

// 辅助函数：把普通段落文字转换为 SRT 格式的字幕文件内容
function textToSRT(text: string, totalDurationSeconds: number): string {
  const sentences = text
    .split(/[，。！？、,;!?\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (sentences.length === 0) return "";

  const avgDuration = totalDurationSeconds / sentences.length;
  let srt = "";

  sentences.forEach((sentence, index) => {
    const startSec = index * avgDuration;
    const endSec = (index + 1) * avgDuration;

    const formatTime = (sec: number) => {
      const hrs = Math.floor(sec / 3600).toString().padStart(2, "0");
      const mins = Math.floor((sec % 3600) / 60).toString().padStart(2, "0");
      const secs = Math.floor(sec % 60).toString().padStart(2, "0");
      const ms = Math.floor((sec % 1) * 1000).toString().padStart(3, "0");
      return `${hrs}:${mins}:${secs},${ms}`;
    };

    srt += `${index + 1}\n`;
    srt += `${formatTime(startSec)} --> ${formatTime(endSec)}\n`;
    srt += `${sentence}\n\n`;
  });

  return srt;
}

function BatchContent() {
  const searchParams = useSearchParams();
  const batchId = searchParams.get("id") || "";

  const [batch, setBatch] = useState<BatchStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [pollingActive, setPollingActive] = useState(true);

  // 磁盘占用状态
  const [storage, setStorage] = useState<{
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    used_percent: number;
  } | null>(null);

  // Modal 状态
  const [selectedVideo, setSelectedVideo] = useState<VideoTask | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [videoCacheBust, setVideoCacheBust] = useState<number>(Date.now());

  // Segment 局部重新生成/上传状态
  const [updatingSegmentIndex, setUpdatingSegmentIndex] = useState<number | null>(null);
  const [uploadingSegmentIndex, setUploadingSegmentIndex] = useState<number | null>(null);

  // Remux 字幕/背景音乐状态
  const [remuxing, setRemuxing] = useState(false);
  const [editedScript, setEditedScript] = useState("");
  const [selectedBgm, setSelectedBgm] = useState("random");
  const [bgmVolume, setBgmVolume] = useState(0.2);

  // 临时编辑状态：Segment 列表深拷贝，以便于在 Modal 内逐项修改并保存
  const [modalSegments, setModalSegments] = useState<ScriptSegment[]>([]);

  // 音频文件参考，视频播放器参考
  const previewVideoRef = useRef<HTMLVideoElement>(null);

  const fetchStatus = useCallback(async () => {
    if (!batchId) return;
    try {
      const data = await getBatchStatus(batchId);
      setBatch(data);

      // 如果 modal 开启着，且选中的视频状态发生了改变，同步更新它以展示最新的状态
      if (selectedVideo) {
        const updatedVideo = data.video_tasks?.find((v) => v.video_id === selectedVideo.video_id);
        if (updatedVideo && updatedVideo.state !== selectedVideo.state) {
          setSelectedVideo(updatedVideo);
        }
      }

      if (
        data.state === "completed" ||
        data.state === "failed" ||
        data.state === "partial_failed"
      ) {
        setPollingActive(false);
      }
    } catch (err) {
      console.error("Failed to fetch batch status:", err);
    } finally {
      setLoading(false);
    }
  }, [batchId, selectedVideo]);

  const fetchStorage = useCallback(async () => {
    try {
      const data = await getStorageStatus();
      setStorage(data);
    } catch (err) {
      console.error("Failed to fetch storage status:", err);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchStorage();
  }, [fetchStatus, fetchStorage]);

  useEffect(() => {
    if (!pollingActive) return;
    const timer = setInterval(() => {
      fetchStatus();
      fetchStorage();
    }, 4000);
    return () => clearInterval(timer);
  }, [pollingActive, fetchStatus, fetchStorage]);

  // 双击卡片触发分镜 Timeline 微调 Modal
  const handleCardDoubleClick = (vt: VideoTask) => {
    setSelectedVideo(vt);
    setModalSegments(JSON.parse(JSON.stringify(vt.variant?.segments || [])));
    setEditedScript(vt.variant?.full_script || "");
    setSelectedBgm(batch?.bgm_file || "random");
    setBgmVolume(0.2);
    setIsModalOpen(true);
    setVideoCacheBust(Date.now());
  };

  // 修改 Timeline 段落局部属性
  const handleSegmentChange = (index: number, key: keyof ScriptSegment, value: any) => {
    const updated = [...modalSegments];
    updated[index] = {
      ...updated[index],
      [key]: value,
    };
    setModalSegments(updated);
  };

  // 单个段落局部重新生成
  const handleRegenerateSegment = async (index: number) => {
    if (!selectedVideo || !batchId) return;
    setUpdatingSegmentIndex(index);
    try {
      const segmentToUpdate = modalSegments[index];
      // 提交到后端仅重新生成该分镜片段并热拼装
      await updateSegment(batchId, selectedVideo.video_id, index, segmentToUpdate);
      
      // 刷新数据与视频缓存
      await fetchStatus();
      await fetchStorage();
      setVideoCacheBust(Date.now());
      
      alert(`分镜 #${index + 1} 重新渲染及视频重拼装已完成！`);
    } catch (err: any) {
      alert(`分镜更新失败: ${err.message || err}`);
    } finally {
      setUpdatingSegmentIndex(null);
    }
  };

  // 局部上传热替换素材
  const handleSegmentFileUpload = async (index: number, file: File) => {
    if (!selectedVideo || !batchId) return;
    setUploadingSegmentIndex(index);
    try {
      // 1. 上传文件到后端临时存储
      const uploadRes = await uploadMaterial(file);
      
      // 2. 更新 segment 数据
      const updatedSegment = {
        ...modalSegments[index],
        material_strategy: "user_upload",
        matched_user_segment_path: uploadRes.file_path,
      };

      const updatedList = [...modalSegments];
      updatedList[index] = updatedSegment;
      setModalSegments(updatedList);

      // 3. 提交后端触发拼装
      await updateSegment(batchId, selectedVideo.video_id, index, updatedSegment);

      // 刷新数据与视频缓存
      await fetchStatus();
      await fetchStorage();
      setVideoCacheBust(Date.now());

      alert(`分镜 #${index + 1} 自定义素材已成功替换并热重拼！`);
    } catch (err: any) {
      alert(`素材上传及拼装失败: ${err.message || err}`);
    } finally {
      setUploadingSegmentIndex(null);
    }
  };

  // 极速字幕与背景音乐热合并 (Remux)
  const handleRemux = async () => {
    if (!selectedVideo || !batchId) return;
    setRemuxing(true);
    try {
      // 智能生成 SRT 格式字幕内容
      const duration = selectedVideo.variant?.estimated_duration || 30;
      const newSrt = textToSRT(editedScript, duration);

      await remuxVideo(batchId, selectedVideo.video_id, {
        new_subtitle_content: newSrt,
        new_bgm_file: selectedBgm,
        bgm_volume: bgmVolume,
      });

      // 刷新数据与视频缓存
      await fetchStatus();
      await fetchStorage();
      setVideoCacheBust(Date.now());

      // 更新口播稿显示
      if (selectedVideo.variant) {
        selectedVideo.variant.full_script = editedScript;
      }

      alert("极速字幕及背景音乐热合并（Remux）已在 3 秒内飞速完成！");
    } catch (err: any) {
      alert(`热合并失败: ${err.message || err}`);
    } finally {
      setRemuxing(false);
    }
  };

  if (!batchId) {
    return (
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "80px 24px", textAlign: "center" }}>
        <h1 style={{ fontSize: 24, fontWeight: 800 }}>❌ 缺少 batch ID</h1>
        <p style={{ color: "var(--text-muted)", marginTop: 12 }}>
          请从任务列表选择一个批量任务
        </p>
        <a href="/" className="btn btn-primary" style={{ marginTop: 24 }}>
          返回首页
        </a>
      </div>
    );
  }

  if (loading || !batch) {
    return (
      <div
        style={{
          maxWidth: 900,
          margin: "0 auto",
          padding: "80px 24px",
          textAlign: "center",
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            border: "4px solid var(--border-subtle)",
            borderTop: "4px solid var(--accent-primary)",
            borderRadius: "50%",
            animation: "spin 0.8s linear infinite",
            margin: "0 auto 16px",
          }}
        />
        <p style={{ color: "var(--text-muted)" }}>加载任务状态...</p>
      </div>
    );
  }

  const batchState = STATE_CONFIG[batch.state] || {
    color: "var(--text-muted)",
    label: batch.state,
    icon: "❓",
  };

  const completedCount = batch.video_tasks?.filter(
    (v) => v.state === "completed"
  ).length || 0;
  const failedCount = batch.video_tasks?.filter(
    (v) => v.state === "failed"
  ).length || 0;
  const totalCount = batch.video_tasks?.length || 0;

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "40px 24px" }}>
      {/* ── 顶部状态栏 ── */}
      <div
        className="glass-card animate-fade-in-up"
        style={{
          padding: 28,
          marginBottom: 32,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 20,
        }}
      >
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 8 }}>
            {batchState.icon} {batch.product_name || "批量任务"}
          </h1>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              fontSize: 13,
              color: "var(--text-muted)",
            }}
          >
            <span>ID: {batchId.slice(0, 12)}...</span>
            <span
              className={`status-badge status-badge--${
                batch.state === "completed"
                  ? "completed"
                  : batch.state === "failed"
                  ? "failed"
                  : "processing"
              }`}
            >
              {batchState.label}
            </span>
          </div>
        </div>

        {/* 磁盘指示器与操作按钮 */}
        <div style={{ display: "flex", alignItems: "center", gap: 28, flexWrap: "wrap" }}>
          {/* HSL 磁盘渐变指示器 */}
          {storage && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                minWidth: 160,
                padding: "8px 16px",
                borderRadius: "var(--radius-md)",
                background: "rgba(255, 255, 255, 0.02)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 11,
                  color: "var(--text-secondary)",
                  fontWeight: 600,
                }}
              >
                <span>💽 缓存磁盘占用</span>
                <span
                  style={{
                    color:
                      storage.used_percent < 60
                        ? "var(--success)"
                        : storage.used_percent < 85
                        ? "var(--warning)"
                        : "var(--danger)",
                  }}
                >
                  {storage.used_percent}%
                </span>
              </div>
              <div className="progress-bar" style={{ height: 6, width: "100%" }}>
                <div
                  style={{
                    height: "100%",
                    width: `${storage.used_percent}%`,
                    borderRadius: 3,
                    backgroundColor:
                      storage.used_percent < 60
                        ? "#00b894" // Neon green
                        : storage.used_percent < 85
                        ? "#fdcb6e" // Glowing gold
                        : "#ff6b6b", // Warning red
                    boxShadow: `0 0 8px ${
                      storage.used_percent < 60
                        ? "rgba(0,184,148,0.4)"
                        : storage.used_percent < 85
                        ? "rgba(253,203,110,0.4)"
                        : "rgba(255,107,107,0.4)"
                    }`,
                    transition: "width 0.4s ease, background-color 0.4s ease",
                  }}
                />
              </div>
              <span style={{ fontSize: 9, color: "var(--text-muted)", textAlign: "right" }}>
                {(storage.used_bytes / 1024 / 1024 / 1024).toFixed(1)} GB /{" "}
                {(storage.total_bytes / 1024 / 1024 / 1024).toFixed(0)} GB (7天自动清理)
              </span>
            </div>
          )}

          <div style={{ display: "flex", gap: 12 }}>
            {completedCount > 0 && (
              <a
                href={getBatchDownloadUrl(batchId)}
                className="btn btn-primary"
                download
                style={{ height: 42, display: "flex", alignItems: "center" }}
              >
                📦 下载全部 ({completedCount})
              </a>
            )}
            <button
              className="btn btn-secondary"
              onClick={() => {
                fetchStatus();
                fetchStorage();
              }}
              style={{ height: 42 }}
            >
              🔄 刷新
            </button>
          </div>
        </div>
      </div>

      {/* ── 整体进度 ── */}
      <div
        className="glass-card animate-fade-in-up"
        style={{ padding: 20, marginBottom: 32, animationDelay: "0.1s" }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: 8,
            fontSize: 13,
          }}
        >
          <span style={{ color: "var(--text-secondary)" }}>总体进度</span>
          <span style={{ fontWeight: 700, color: "var(--accent-secondary)" }}>
            {Math.round(batch.progress)}%
          </span>
        </div>
        <div className="progress-bar" style={{ height: 8 }}>
          <div
            className="progress-bar-fill"
            style={{ width: `${batch.progress}%` }}
          />
        </div>
        <div
          style={{
            display: "flex",
            gap: 24,
            marginTop: 12,
            fontSize: 12,
            color: "var(--text-muted)",
          }}
        >
          <span>总计 {totalCount} 条</span>
          <span style={{ color: "var(--success)" }}>✅ 完成 {completedCount}</span>
          {failedCount > 0 && (
            <span style={{ color: "var(--danger)" }}>❌ 失败 {failedCount}</span>
          )}
          <span>🔄 进行中 {totalCount - completedCount - failedCount}</span>
        </div>
      </div>

      {/* ── 视频列表标题与提示 ── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
        }}
      >
        <h2 style={{ fontSize: 20, fontWeight: 800 }}>🎬 视频列表</h2>
        <span
          style={{
            fontSize: 12,
            color: "var(--accent-secondary)",
            background: "rgba(162, 155, 254, 0.1)",
            padding: "4px 12px",
            borderRadius: 20,
            border: "1px solid rgba(162, 155, 254, 0.2)",
            fontWeight: 500,
          }}
        >
          💡 提示：双击任一卡片开启「分镜故事板」 Timeline 局部微调与热合并
        </span>
      </div>

      {/* ── 视频网格 ── */}
      <div className="video-grid">
        {(batch.video_tasks || []).map((vt: VideoTask) => {
          const vtState = STATE_CONFIG[vt.state] || {
            color: "var(--text-muted)",
            label: vt.state,
            icon: "❓",
          };
          const isCompleted = vt.state === "completed";

          return (
            <div
              key={vt.video_id}
              className="video-card"
              onDoubleClick={() => handleCardDoubleClick(vt)}
              style={{ cursor: "pointer", position: "relative" }}
              title="双击进行局部微调或热合并"
            >
              {/* 卡片双击引导悬浮层 */}
              <div
                className="card-hover-overlay"
                style={{
                  position: "absolute",
                  top: 8,
                  left: 8,
                  zIndex: 10,
                  pointerEvents: "none",
                  display: "flex",
                  gap: 6,
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    background: "rgba(10, 10, 15, 0.75)",
                    backdropFilter: "blur(4px)",
                    color: "var(--text-secondary)",
                    padding: "3px 8px",
                    borderRadius: 12,
                    border: "1px solid var(--border-subtle)",
                    fontWeight: 600,
                  }}
                >
                  ⚡ 双击微调
                </span>
              </div>

              {/* 预览区 */}
              <div className="video-card__preview">
                {isCompleted ? (
                  <video
                    src={`${getVideoPreviewUrl(batchId, vt.video_id)}?t=${videoCacheBust}`}
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "cover",
                    }}
                    controls
                    preload="metadata"
                  />
                ) : (
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: 12,
                      color: "var(--text-muted)",
                    }}
                  >
                    <div style={{ fontSize: 36, animation: vt.state !== "failed" ? "pulse 2s infinite" : "none" }}>
                      {vtState.icon}
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{vtState.label}</div>
                    {vt.progress > 0 && vt.progress < 100 && (
                      <div style={{ width: 100 }}>
                        <div className="progress-bar">
                          <div
                            className="progress-bar-fill"
                            style={{ width: `${vt.progress}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 信息区 */}
              <div className="video-card__info">
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 700,
                      color: "var(--accent-secondary)",
                    }}
                  >
                    {vt.variant?.style || vt.video_id}
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      color: vtState.color,
                      fontWeight: 600,
                    }}
                  >
                    {vtState.label}
                  </span>
                </div>

                {vt.variant?.full_script && (
                  <p
                    style={{
                      fontSize: 12,
                      color: "var(--text-muted)",
                      lineHeight: 1.5,
                      overflow: "hidden",
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical" as any,
                    }}
                  >
                    {vt.variant.full_script}
                  </p>
                )}

                {vt.error && (
                  <p
                    style={{
                      fontSize: 11,
                      color: "var(--danger)",
                      padding: "4px 8px",
                      background: "rgba(255,107,107,0.08)",
                      borderRadius: 6,
                      wordBreak: "break-all",
                    }}
                  >
                    {vt.error}
                  </p>
                )}

                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    marginTop: 4,
                  }}
                >
                  {isCompleted && (
                    <a
                      href={getVideoDownloadUrl(batchId, vt.video_id)}
                      className="btn btn-secondary"
                      download
                      style={{
                        fontSize: 12,
                        padding: "6px 12px",
                        flex: 1,
                      }}
                    >
                      ⬇️ 下载成片
                    </a>
                  )}
                  <button
                    className="btn btn-ghost"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCardDoubleClick(vt);
                    }}
                    style={{
                      fontSize: 12,
                      padding: "6px 12px",
                      border: "1px dashed var(--border-accent)",
                      borderRadius: "var(--radius-md)",
                      color: "var(--accent-secondary)",
                      flex: isCompleted ? 0 : 1,
                    }}
                  >
                    ⚙️ 极速微调
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── 极风霓虹玻璃态 Timeline 微调故事板 Modal ── */}
      {isModalOpen && selectedVideo && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(6, 6, 9, 0.85)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
          }}
          onClick={() => setIsModalOpen(false)}
        >
          <div
            className="glass-card animate-fade-in-up"
            style={{
              width: "100%",
              maxWidth: 1200,
              height: "85vh",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              border: "1px solid var(--border-accent)",
              boxShadow: "0 0 50px rgba(108, 92, 231, 0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal 头部 */}
            <div
              style={{
                padding: "20px 24px",
                borderBottom: "1px solid var(--border-subtle)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "rgba(22, 22, 31, 0.4)",
              }}
            >
              <div>
                <h3 style={{ fontSize: 18, fontWeight: 800, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: 10 }}>
                  <span>⚙️ 分镜故事板 Timeline 微调</span>
                  <span style={{ fontSize: 13, background: "rgba(108, 92, 231, 0.15)", color: "var(--accent-secondary)", padding: "3px 10px", borderRadius: 12, border: "1px solid rgba(108, 92, 231, 0.3)" }}>
                    风格: {selectedVideo.variant?.style} ({selectedVideo.video_id})
                  </span>
                </h3>
                <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                  局部微调分镜画面可以在 10 秒内局部重编拼接；极速字幕与背景音乐热合并仅耗时 3 秒！
                </p>
              </div>
              <button
                className="btn btn-ghost"
                onClick={() => setIsModalOpen(false)}
                style={{ padding: 8, minWidth: 36, height: 36, borderRadius: "50%", fontSize: 18 }}
              >
                ✖
              </button>
            </div>

            {/* Modal 主体 */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "380px 1fr",
                height: "calc(100% - 77px)",
                overflow: "hidden",
              }}
            >
              {/* 左栏：视频播放器与 3s 热合并 Remux 面板 */}
              <div
                style={{
                  borderRight: "1px solid var(--border-subtle)",
                  padding: 24,
                  display: "flex",
                  flexDirection: "column",
                  gap: 20,
                  overflowY: "auto",
                  background: "rgba(10, 10, 15, 0.3)",
                }}
              >
                {/* 视频实时预览 */}
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div
                    style={{
                      aspectRatio: "9/16",
                      width: "100%",
                      maxHeight: "360px",
                      borderRadius: "var(--radius-md)",
                      overflow: "hidden",
                      background: "#000",
                      border: "1px solid var(--border-subtle)",
                      position: "relative",
                      boxShadow: "var(--shadow-glow)",
                    }}
                  >
                    {selectedVideo.state === "completed" ? (
                      <video
                        ref={previewVideoRef}
                        src={`${getVideoPreviewUrl(batchId, selectedVideo.video_id)}?t=${videoCacheBust}`}
                        style={{ width: "100%", height: "100%", objectFit: "cover" }}
                        controls
                        autoPlay
                        preload="metadata"
                      />
                    ) : (
                      <div
                        style={{
                          width: "100%",
                          height: "100%",
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: 12,
                          color: "var(--text-muted)",
                          padding: 20,
                          textAlign: "center",
                        }}
                      >
                        <div style={{ fontSize: 32, animation: "spin 2s linear infinite" }}>🔄</div>
                        <div style={{ fontSize: 13, color: "var(--accent-secondary)", fontWeight: 600 }}>
                          后端正在生成拼装视频中...
                        </div>
                        <div style={{ fontSize: 11 }}>
                          状态: {STATE_CONFIG[selectedVideo.state]?.label || selectedVideo.state} ({Math.round(selectedVideo.progress)}%)
                        </div>
                      </div>
                    )}
                  </div>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "8px 12px", fontSize: 12 }}
                    onClick={() => setVideoCacheBust(Date.now())}
                    disabled={selectedVideo.state !== "completed"}
                  >
                    🔄 强制重载视频播放器
                  </button>
                </div>

                {/* 3秒热合并 Remux 控制面板 */}
                <div
                  className="glass-card"
                  style={{
                    padding: 16,
                    border: "1px solid var(--border-accent)",
                    background: "rgba(108, 92, 231, 0.03)",
                  }}
                >
                  <h4 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: "var(--accent-secondary)", display: "flex", alignItems: "center", gap: 6 }}>
                    <span>⚡ 极速字幕与背景音乐热合并 (3秒)</span>
                  </h4>

                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {/* 字幕/口播编辑 */}
                    <div className="form-group">
                      <label className="form-label" style={{ fontSize: 11 }}>整段口播字幕内容</label>
                      <textarea
                        className="form-textarea"
                        value={editedScript}
                        onChange={(e) => setEditedScript(e.target.value)}
                        style={{ minHeight: 80, fontSize: 12, padding: "8px 12px" }}
                        placeholder="编辑此处的口播脚本文字，保存后将免渲染极速热合并字幕音频..."
                      />
                    </div>

                    {/* BGM 更改 */}
                    <div className="form-group">
                      <label className="form-label" style={{ fontSize: 11 }}>选择背景音乐 BGM</label>
                      <select
                        className="form-select"
                        value={selectedBgm}
                        onChange={(e) => setSelectedBgm(e.target.value)}
                        style={{ fontSize: 12, padding: "8px 12px" }}
                      >
                        <option value="random">🎵 随机库中匹配</option>
                        <option value="bgm1.mp3">🎵 欢快流行 (Upbeat Pop)</option>
                        <option value="bgm2.mp3">🎵 动感电子 (Energetic Electro)</option>
                        <option value="bgm3.mp3">🎵 舒缓轻音乐 (Smooth Ambient)</option>
                        <option value="bgm4.mp3">🎵 燃爆史诗 (Epic Burn)</option>
                        <option value="none">🔇 无背景音乐</option>
                      </select>
                    </div>

                    {/* BGM 音量 */}
                    <div className="form-group">
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                        <span className="form-label" style={{ fontSize: 11 }}>背景音乐音量</span>
                        <span style={{ color: "var(--accent-secondary)" }}>{Math.round(bgmVolume * 100)}%</span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={bgmVolume}
                        onChange={(e) => setBgmVolume(parseFloat(e.target.value))}
                        style={{ accentColor: "var(--accent-primary)", marginTop: 4 }}
                      />
                    </div>

                    {/* 提交 Remux */}
                    <button
                      className="btn btn-primary"
                      onClick={handleRemux}
                      disabled={remuxing || selectedVideo.state !== "completed"}
                      style={{ fontSize: 12, padding: "10px 16px", marginTop: 8 }}
                    >
                      {remuxing ? (
                        <>
                          <div
                            style={{
                              width: 14,
                              height: 14,
                              border: "2px solid rgba(255,255,255,0.3)",
                              borderTop: "2px solid #fff",
                              borderRadius: "50%",
                              animation: "spin 0.6s linear infinite",
                            }}
                          />
                          <span>正在瞬时热合并...</span>
                        </>
                      ) : (
                        <span>🚀 极速合并字幕/BGM (3s)</span>
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* 右栏：滚动 Timeline 分镜微调卡片 */}
              <div
                style={{
                  padding: 24,
                  overflowY: "auto",
                  display: "flex",
                  flexDirection: "column",
                  gap: 16,
                }}
              >
                <h4 style={{ fontSize: 15, fontWeight: 800, marginBottom: 4, display: "flex", alignItems: "center", gap: 8 }}>
                  <span>🎬 视频自然分镜 Timeline</span>
                  <span style={{ fontSize: 11, fontWeight: 400, color: "var(--text-muted)" }}>
                    共计 {modalSegments.length} 个镜头自然段落
                  </span>
                </h4>

                {modalSegments.map((seg, idx) => {
                  const isUpdating = updatingSegmentIndex === idx;
                  const isUploading = uploadingSegmentIndex === idx;

                  return (
                    <div
                      key={idx}
                      className="glass-card"
                      style={{
                        padding: 20,
                        borderLeft: `4px solid ${
                          seg.material_strategy === "user_upload"
                            ? "var(--success)"
                            : seg.material_strategy.startsWith("ai_")
                            ? "var(--accent-primary)"
                            : "var(--warning)"
                        }`,
                        background: "rgba(255, 255, 255, 0.01)",
                        display: "grid",
                        gridTemplateColumns: "1fr",
                        gap: 16,
                        position: "relative",
                        transition: "all var(--transition-fast)",
                      }}
                    >
                      {/* 分镜头部 */}
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          borderBottom: "1px solid var(--border-subtle)",
                          paddingBottom: 10,
                        }}
                      >
                        <span style={{ fontWeight: 800, fontSize: 13, color: "var(--accent-secondary)" }}>
                          #分镜镜头 {idx + 1}
                        </span>

                        {/* 策略选择 */}
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>素材策略:</span>
                          <select
                            className="form-select"
                            value={seg.material_strategy}
                            onChange={(e) => handleSegmentChange(idx, "material_strategy", e.target.value)}
                            style={{ padding: "4px 8px", fontSize: 11, height: 26 }}
                          >
                            <option value="ai_image">🎨 Flux AI 生成图</option>
                            <option value="ai_video">🎥 Luma AI 生成视频</option>
                            <option value="stock">🎬 pexels 素材库检索</option>
                            <option value="user_upload">📤 自定义本地上传替换</option>
                          </select>
                        </div>
                      </div>

                      {/* 编辑表单 */}
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                        <div className="form-group">
                          <label className="form-label" style={{ fontSize: 11 }}>本段口播旁白字幕</label>
                          <textarea
                            className="form-textarea"
                            value={seg.text}
                            onChange={(e) => handleSegmentChange(idx, "text", e.target.value)}
                            style={{ minHeight: 60, fontSize: 12 }}
                            placeholder="输入此分镜对应的单句口播配音旁白..."
                          />
                        </div>

                        <div className="form-group">
                          <label className="form-label" style={{ fontSize: 11 }}>画面 AI 生图/视频 Prompt</label>
                          <textarea
                            className="form-textarea"
                            value={seg.ai_prompt}
                            onChange={(e) => handleSegmentChange(idx, "ai_prompt", e.target.value)}
                            style={{ minHeight: 60, fontSize: 12 }}
                            placeholder="为当前分镜指定精准的画面描述 AI 提示词..."
                            disabled={seg.material_strategy === "stock" || seg.material_strategy === "user_upload"}
                          />
                        </div>
                      </div>

                      {/* 动作栏 */}
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginTop: 4,
                        }}
                      >
                        {/* 用户自定义上传控件 */}
                        {seg.material_strategy === "user_upload" ? (
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <label className="btn btn-secondary" style={{ padding: "6px 12px", fontSize: 11, cursor: "pointer" }}>
                              {isUploading ? "正在极速上传中..." : "📤 上传本地 MP4/图片替换"}
                              <input
                                type="file"
                                accept="video/*,image/*"
                                style={{ display: "none" }}
                                onChange={(e) => {
                                  const file = e.target.files?.[0];
                                  if (file) handleSegmentFileUpload(idx, file);
                                }}
                                disabled={isUploading}
                              />
                            </label>
                            {seg.matched_user_segment_path && (
                              <span
                                style={{ fontSize: 10, color: "var(--success)", textOverflow: "ellipsis", overflow: "hidden", maxWidth: 180, whiteSpace: "nowrap" }}
                                title={seg.matched_user_segment_path}
                              >
                                已加载: {seg.matched_user_segment_path.split("/").pop()}
                              </span>
                            )}
                          </div>
                        ) : (
                          <div />
                        )}

                        {/* 单镜头重渲染保存 */}
                        <button
                          className="btn btn-secondary"
                          onClick={() => handleRegenerateSegment(idx)}
                          disabled={isUpdating || isUploading || selectedVideo.state !== "completed"}
                          style={{
                            borderColor: "var(--border-accent)",
                            color: "var(--accent-secondary)",
                            padding: "6px 16px",
                            fontSize: 12,
                          }}
                        >
                          {isUpdating ? (
                            <>
                              <div
                                style={{
                                  width: 12,
                                  height: 12,
                                  border: "2px solid rgba(108,92,231,0.3)",
                                  borderTop: "2px solid var(--accent-primary)",
                                  borderRadius: "50%",
                                  animation: "spin 0.6s linear infinite",
                                }}
                              />
                              <span>正在更新并热拼装...</span>
                            </>
                          ) : (
                            <span>🔄 局部重新生成 (10s)</span>
                          )}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function BatchPage() {
  return (
    <Suspense
      fallback={
        <div style={{ maxWidth: 900, margin: "0 auto", padding: "80px 24px", textAlign: "center" }}>
          <div
            style={{
              width: 40,
              height: 40,
              border: "4px solid var(--border-subtle)",
              borderTop: "4px solid var(--accent-primary)",
              borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
              margin: "0 auto 16px",
            }}
          />
          <p style={{ color: "var(--text-muted)" }}>加载中...</p>
        </div>
      }
    >
      <BatchContent />
    </Suspense>
  );
}
