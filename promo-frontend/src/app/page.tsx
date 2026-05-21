"use client";

import { useEffect, useState } from "react";
import { listBatches, type BatchStatus } from "@/lib/api";

export default function HomePage() {
  const [batches, setBatches] = useState<BatchStatus[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadBatches();
  }, []);

  async function loadBatches() {
    try {
      const data = await listBatches();
      setBatches(data.batches || []);
    } catch {
      // API not available, show empty state
    } finally {
      setLoading(false);
    }
  }

  const stateColors: Record<string, string> = {
    analyzing: "var(--info)",
    scripting: "var(--accent-secondary)",
    generating: "var(--accent-primary)",
    completed: "var(--success)",
    partial_failed: "var(--warning)",
    failed: "var(--danger)",
  };

  const stateLabels: Record<string, string> = {
    analyzing: "分析中",
    scripting: "文案生成",
    generating: "视频生成中",
    completed: "已完成",
    partial_failed: "部分失败",
    failed: "失败",
  };

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "48px 24px" }}>
      {/* ── Hero Section ── */}
      <div
        className="animate-fade-in-up"
        style={{ textAlign: "center", marginBottom: 64 }}
      >
        <h1
          style={{
            fontSize: 48,
            fontWeight: 900,
            lineHeight: 1.2,
            marginBottom: 16,
          }}
        >
          <span className="accent-gradient-text">AI 驱动</span>的
          <br />
          抖音推广视频批量工作台
        </h1>
        <p
          style={{
            fontSize: 18,
            color: "var(--text-secondary)",
            maxWidth: 560,
            margin: "0 auto 32px",
            lineHeight: 1.6,
          }}
        >
          上传素材 → AI 优化口播稿 → 生成多风格变体 → 批量合成高质量推广视频
        </p>
        <a
          href="/create"
          className="btn btn-primary"
          style={{ padding: "16px 40px", fontSize: 16, borderRadius: 14 }}
        >
          ✨ 开始创建推广视频
        </a>
      </div>

      {/* ── 功能卡片 ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 20,
          marginBottom: 64,
        }}
      >
        {[
          {
            icon: "🎯",
            title: "智能口播稿优化",
            desc: "AI 理解产品核心卖点，自动补全和优化不完整的口播稿",
          },
          {
            icon: "🎨",
            title: "6 种风格变体",
            desc: "热情激昂、专业知性、轻松种草、紧迫促销、故事叙事、对比测评",
          },
          {
            icon: "🎬",
            title: "混合素材策略",
            desc: "AI 文生图/视频 + 用户素材 + Pexels/Pixabay 素材库智能组合",
          },
          {
            icon: "🔊",
            title: "多音色 TTS",
            desc: "每条视频自动分配不同 AI 音色，增加内容多样性",
          },
        ].map((feature, i) => (
          <div
            key={i}
            className="glass-card animate-fade-in-up"
            style={{
              padding: 28,
              animationDelay: `${i * 100}ms`,
            }}
          >
            <div style={{ fontSize: 36, marginBottom: 12 }}>{feature.icon}</div>
            <h3
              style={{
                fontSize: 16,
                fontWeight: 700,
                marginBottom: 8,
                color: "var(--text-primary)",
              }}
            >
              {feature.title}
            </h3>
            <p
              style={{
                fontSize: 13,
                color: "var(--text-secondary)",
                lineHeight: 1.6,
              }}
            >
              {feature.desc}
            </p>
          </div>
        ))}
      </div>

      {/* ── 任务列表 ── */}
      <div>
        <h2
          style={{
            fontSize: 24,
            fontWeight: 800,
            marginBottom: 24,
          }}
        >
          📋 最近任务
        </h2>

        {loading ? (
          <div
            className="glass-card"
            style={{
              padding: 48,
              textAlign: "center",
              color: "var(--text-muted)",
            }}
          >
            <div
              style={{
                width: 32,
                height: 32,
                border: "3px solid var(--border-subtle)",
                borderTop: "3px solid var(--accent-primary)",
                borderRadius: "50%",
                animation: "spin 0.8s linear infinite",
                margin: "0 auto 16px",
              }}
            />
            加载中...
          </div>
        ) : batches.length === 0 ? (
          <div
            className="glass-card"
            style={{
              padding: 64,
              textAlign: "center",
              color: "var(--text-muted)",
            }}
          >
            <div style={{ fontSize: 48, marginBottom: 16 }}>📭</div>
            <p style={{ fontSize: 16, marginBottom: 24 }}>还没有任务</p>
            <a href="/create" className="btn btn-primary">
              创建第一个推广任务
            </a>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {batches.map((batch) => (
              <a
                key={batch.batch_id}
                href={`/batch?id=${batch.batch_id}`}
                className="glass-card"
                style={{
                  padding: 20,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  textDecoration: "none",
                  color: "inherit",
                  transition: "all var(--transition-normal)",
                  cursor: "pointer",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontWeight: 700,
                        fontSize: 15,
                        marginBottom: 4,
                      }}
                    >
                      {batch.product_name || "未命名任务"}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--text-muted)",
                      }}
                    >
                      {batch.video_tasks?.length || 0} 条视频 · ID:{" "}
                      {batch.batch_id.slice(0, 8)}
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  {/* 进度条 */}
                  <div style={{ width: 120 }}>
                    <div className="progress-bar">
                      <div
                        className="progress-bar-fill"
                        style={{ width: `${batch.progress}%` }}
                      />
                    </div>
                  </div>

                  {/* 状态标签 */}
                  <span
                    className={`status-badge status-badge--${batch.state === "completed" ? "completed" : batch.state === "failed" ? "failed" : "processing"}`}
                  >
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: stateColors[batch.state] || "var(--text-muted)",
                      }}
                    />
                    {stateLabels[batch.state] || batch.state}
                  </span>
                </div>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
