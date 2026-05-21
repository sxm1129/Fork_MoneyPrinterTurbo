"use client";

import { useState, useRef, useCallback } from "react";
import {
  uploadMaterial,
  optimizeScript,
  generateVariants,
  createBatch,
  getStyles,
  diagnoseScript,
  type ScriptVariant,
} from "@/lib/api";

type WizardStep =
  | "product"
  | "material"
  | "script"
  | "variants"
  | "config"
  | "submit";

const STEP_ORDER: WizardStep[] = [
  "product",
  "material",
  "script",
  "variants",
  "config",
  "submit",
];

const STEP_LABELS: Record<WizardStep, string> = {
  product: "产品信息",
  material: "素材上传",
  script: "口播稿",
  variants: "风格变体",
  config: "生成配置",
  submit: "提交",
};

export default function CreatePage() {
  const [step, setStep] = useState<WizardStep>("product");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ── Step 1: 产品信息
  const [productName, setProductName] = useState("");
  const [productDesc, setProductDesc] = useState("");
  const [livestreamPurpose, setLivestreamPurpose] = useState("");

  // ── Step 2: 素材
  const [materialIds, setMaterialIds] = useState<string[]>([]);
  const [uploadedFiles, setUploadedFiles] = useState<
    { id: string; name: string }[]
  >([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Step 3: 口播稿
  const [rawScript, setRawScript] = useState("");
  const [optimizedScript, setOptimizedScript] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("");

  // ── Step 4: 变体
  const [variants, setVariants] = useState<ScriptVariant[]>([]);
  const [variantCount, setVariantCount] = useState(5);
  const [selectedVariants, setSelectedVariants] = useState<Set<string>>(
    new Set()
  );
  const [diagnoseResult, setDiagnoseResult] = useState<any>(null);
  const [diagnoseLoading, setDiagnoseLoading] = useState(false);

  // ── Step 5: 配置
  const [videoAspect, setVideoAspect] = useState("9:16");
  const [subtitleEnabled, setSubtitleEnabled] = useState(true);
  const [maxConcurrent, setMaxConcurrent] = useState(3);
  const [motionIntensity, setMotionIntensity] = useState(1.0);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [ctaPrice, setCtaPrice] = useState("");
  const [ctaOriginalPrice, setCtaOriginalPrice] = useState("");
  const [ctaText, setCtaText] = useState("");

  // ── Step 6: 结果
  const [batchId, setBatchId] = useState("");

  const currentIdx = STEP_ORDER.indexOf(step);

  // ────────── 素材上传 ──────────
  const handleFileUpload = useCallback(
    async (files: FileList | null) => {
      if (!files) return;
      setLoading(true);
      setError("");

      for (const file of Array.from(files)) {
        try {
          const result = await uploadMaterial(file);
          setMaterialIds((prev) => [...prev, result.material_id]);
          setUploadedFiles((prev) => [
            ...prev,
            { id: result.material_id, name: result.filename },
          ]);
        } catch (e: any) {
          setError(`上传失败: ${e.message}`);
        }
      }
      setLoading(false);
    },
    []
  );

  // ────────── 口播稿优化 ──────────
  const handleOptimize = async () => {
    if (!rawScript.trim()) {
      setError("请输入原始口播稿");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await optimizeScript(
        rawScript,
        productName,
        productDesc,
        livestreamPurpose,
        targetLanguage
      );
      setOptimizedScript(result.optimized_script);
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  // ────────── 口播稿爆款雷达诊断 ──────────
  const handleDiagnose = async () => {
    const textToDiagnose = optimizedScript || rawScript;
    if (!textToDiagnose.trim()) {
      setError("请先输入原始口播稿或生成优化稿以进行诊断");
      return;
    }
    setDiagnoseLoading(true);
    setError("");
    setDiagnoseResult(null);
    try {
      const result = await diagnoseScript(textToDiagnose, productName);
      setDiagnoseResult(result);
    } catch (e: any) {
      setError(`诊断失败: ${e.message}`);
    }
    setDiagnoseLoading(false);
  };

  // ────────── 生成变体 ──────────
  const handleGenerateVariants = async () => {
    if (!optimizedScript.trim()) {
      setError("请先优化口播稿");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await generateVariants(
        optimizedScript,
        productName,
        undefined,
        variantCount,
        targetLanguage
      );
      setVariants(result.variants);
      setSelectedVariants(
        new Set(result.variants.map((v) => v.variant_id))
      );
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  // ────────── 提交批量任务 ──────────
  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    try {
      const selectedVars = variants.filter((v) =>
        selectedVariants.has(v.variant_id)
      );
      const result = await createBatch({
        product_name: productName,
        raw_script: rawScript,
        product_description: productDesc,
        livestream_purpose: livestreamPurpose,
        variants: selectedVars,
        material_ids: materialIds,
        video_aspect: videoAspect,
        subtitle_enabled: subtitleEnabled,
        max_concurrent: maxConcurrent,
        motion_intensity: motionIntensity,
        cta_config: ctaPrice ? {
          price: ctaPrice,
          original_price: ctaOriginalPrice || undefined,
          cta_text: ctaText || undefined,
        } : null,
        webhook_url: webhookUrl || undefined,
      });
      setBatchId(result.batch_id);
      setStep("submit");
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  // ────────── 步骤导航 ──────────
  const canGoNext = () => {
    switch (step) {
      case "product":
        return productName.trim().length > 0;
      case "material":
        return true; // optional
      case "script":
        return optimizedScript.trim().length > 0;
      case "variants":
        return selectedVariants.size > 0;
      case "config":
        return true;
      default:
        return false;
    }
  };

  const goNext = () => {
    if (currentIdx < STEP_ORDER.length - 1) {
      setError("");
      setStep(STEP_ORDER[currentIdx + 1]);
    }
  };

  const goPrev = () => {
    if (currentIdx > 0) {
      setError("");
      setStep(STEP_ORDER[currentIdx - 1]);
    }
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 24px" }}>
      {/* ── 向导步骤条 ── */}
      <div className="wizard-steps">
        {STEP_ORDER.map((s, i) => (
          <div key={s} style={{ display: "flex", alignItems: "center", flex: i < STEP_ORDER.length - 1 ? 1 : "none" }}>
            <div
              className={`wizard-step ${
                i < currentIdx
                  ? "wizard-step--done"
                  : i === currentIdx
                  ? "wizard-step--active"
                  : ""
              }`}
              style={{ cursor: i < currentIdx ? "pointer" : "default" }}
              onClick={() => i < currentIdx && setStep(s)}
            >
              <div className="wizard-step__number">
                {i < currentIdx ? "✓" : i + 1}
              </div>
              <span className="wizard-step__label">{STEP_LABELS[s]}</span>
            </div>
            {i < STEP_ORDER.length - 1 && (
              <div
                className="wizard-step__connector"
                style={{
                  background:
                    i < currentIdx
                      ? "var(--accent-primary)"
                      : "var(--border-subtle)",
                }}
              />
            )}
          </div>
        ))}
      </div>

      {/* ── 错误提示 ── */}
      {error && (
        <div
          style={{
            padding: "12px 20px",
            background: "rgba(255,107,107,0.1)",
            border: "1px solid rgba(255,107,107,0.3)",
            borderRadius: "var(--radius-md)",
            color: "var(--danger)",
            fontSize: 14,
            marginBottom: 24,
          }}
        >
          ⚠️ {error}
        </div>
      )}

      {/* ── Step Content ── */}
      <div
        className="glass-card animate-fade-in-up"
        style={{ padding: 32, marginBottom: 24 }}
      >
        {/* ───── Step 1: 产品信息 ───── */}
        {step === "product" && (
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 24 }}>
              📦 产品信息
            </h2>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 20,
              }}
            >
              <div className="form-group">
                <label className="form-label">产品名称 *</label>
                <input
                  className="form-input"
                  placeholder="如：资生堂面膜"
                  value={productName}
                  onChange={(e) => setProductName(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">产品描述</label>
                <textarea
                  className="form-textarea"
                  placeholder="产品核心卖点、成分、功效等"
                  value={productDesc}
                  onChange={(e) => setProductDesc(e.target.value)}
                  rows={3}
                />
              </div>
              <div className="form-group">
                <label className="form-label">直播目的</label>
                <select
                  className="form-select"
                  value={livestreamPurpose}
                  onChange={(e) => setLivestreamPurpose(e.target.value)}
                >
                  <option value="">选择目的</option>
                  <option value="新品推广">新品推广</option>
                  <option value="清仓促销">清仓促销</option>
                  <option value="品牌宣传">品牌宣传</option>
                  <option value="节日活动">节日活动</option>
                  <option value="日常引流">日常引流</option>
                </select>
              </div>
            </div>
          </div>
        )}

        {/* ───── Step 2: 素材上传 ───── */}
        {step === "material" && (
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 8 }}>
              📁 素材上传
            </h2>
            <p
              style={{
                color: "var(--text-secondary)",
                fontSize: 14,
                marginBottom: 24,
              }}
            >
              上传产品相关的视频或图片素材（可选，可跳过使用 AI 生成素材）
            </p>

            <div
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: "2px dashed var(--border-accent)",
                borderRadius: "var(--radius-lg)",
                padding: 48,
                textAlign: "center",
                cursor: "pointer",
                transition: "all var(--transition-normal)",
                background: "rgba(108, 92, 231, 0.03)",
              }}
              onDragOver={(e) => {
                e.preventDefault();
                e.currentTarget.style.background =
                  "rgba(108, 92, 231, 0.08)";
              }}
              onDragLeave={(e) => {
                e.currentTarget.style.background =
                  "rgba(108, 92, 231, 0.03)";
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.currentTarget.style.background =
                  "rgba(108, 92, 231, 0.03)";
                handleFileUpload(e.dataTransfer.files);
              }}
            >
              <div
                style={{ fontSize: 40, marginBottom: 12, opacity: 0.7 }}
              >
                📤
              </div>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                点击或拖拽上传素材
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: "var(--text-muted)",
                }}
              >
                支持 MP4, MOV, JPG, PNG（单个最大 100MB）
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="video/*,image/*"
              style={{ display: "none" }}
              onChange={(e) => handleFileUpload(e.target.files)}
            />

            {uploadedFiles.length > 0 && (
              <div style={{ marginTop: 20 }}>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: "var(--text-secondary)",
                    marginBottom: 8,
                  }}
                >
                  已上传 {uploadedFiles.length} 个文件
                </div>
                {uploadedFiles.map((f) => (
                  <div
                    key={f.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "8px 12px",
                      background: "var(--bg-elevated)",
                      borderRadius: "var(--radius-sm)",
                      marginBottom: 6,
                      fontSize: 13,
                    }}
                  >
                    <span style={{ color: "var(--success)" }}>✓</span>
                    <span>{f.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ───── Step 3: 口播稿 ───── */}
        {step === "script" && (
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 24 }}>
              📝 口播稿优化
            </h2>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">原始口播稿</label>
              <textarea
                className="form-textarea"
                placeholder="输入原始口播稿（可以不完整，AI 会自动补全和优化）"
                value={rawScript}
                onChange={(e) => setRawScript(e.target.value)}
                rows={4}
              />
            </div>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">目标语言（出海多语系翻译）</label>
              <select
                className="form-select"
                value={targetLanguage}
                onChange={(e) => setTargetLanguage(e.target.value)}
              >
                <option value="">保持原语言 (默认中文)</option>
                <option value="English">英语 (English)</option>
                <option value="Japanese">日语 (日本語)</option>
                <option value="Korean">韩语 (한국어)</option>
                <option value="Spanish">西班牙语 (Español)</option>
                <option value="French">法语 (Français)</option>
              </select>
            </div>

            <button
              className="btn btn-primary"
              onClick={handleOptimize}
              disabled={loading || !rawScript.trim()}
              style={{ marginBottom: 20 }}
            >
              {loading ? "⏳ AI 优化中..." : "🪄 AI 优化口播稿"}
            </button>

            {optimizedScript && (
              <div className="form-group">
                <label className="form-label">
                  ✅ 优化后的标准稿（可编辑）
                </label>
                <textarea
                  className="form-textarea"
                  value={optimizedScript}
                  onChange={(e) => setOptimizedScript(e.target.value)}
                  rows={5}
                  style={{
                    borderColor: "rgba(0, 184, 148, 0.3)",
                    background: "rgba(0, 184, 148, 0.05)",
                  }}
                />
              </div>
            )}
          </div>
        )}

        {/* ───── Step 4: 风格变体 ───── */}
        {step === "variants" && (
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 8 }}>
              🎨 风格变体 & 爆款诊断
            </h2>
            <p
              style={{
                color: "var(--text-secondary)",
                fontSize: 14,
                marginBottom: 20,
              }}
            >
              基于标准稿生成多种风格的变体，每条变体将生成一个独立的推广视频
            </p>

            {/* 爆款文案雷达诊断按钮及界面 */}
            <div
              className="glass-card"
              style={{
                padding: 24,
                marginBottom: 24,
                border: "1px dashed var(--border-accent)",
                background: "rgba(108, 92, 231, 0.02)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 12,
                  marginBottom: 16,
                }}
              >
                <div>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                    📡 AI 爆款潜力诊断雷达
                  </h3>
                  <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
                    基于抖音爆款算法库，对当前口播文案进行黄金3秒吸睛力、说服力、流畅度、行动召唤四维深度诊断打分
                  </p>
                </div>
                <button
                  className="btn btn-secondary animate-pulse-glow"
                  onClick={handleDiagnose}
                  disabled={diagnoseLoading || (!optimizedScript.trim() && !rawScript.trim())}
                  style={{ border: "1px solid var(--accent-primary)" }}
                >
                  {diagnoseLoading ? "⏳ 深度分析中..." : "🔍 爆款潜力诊断"}
                </button>
              </div>

              {/* 诊断结果渲染 */}
              {diagnoseResult && (
                <div style={{ marginTop: 20 }} className="animate-fade-in-up">
                  {/* SVG 定义渐变 */}
                  <svg style={{ height: 0, width: 0, position: 'absolute' }}>
                    <defs>
                      <linearGradient id="neon-grad-hook" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="#6c5ce7" />
                        <stop offset="100%" stopColor="#fd79a8" />
                      </linearGradient>
                      <linearGradient id="neon-grad-conversion" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="#00b894" />
                        <stop offset="100%" stopColor="#55efc4" />
                      </linearGradient>
                      <linearGradient id="neon-grad-fluency" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="#74b9ff" />
                        <stop offset="100%" stopColor="#a29bfe" />
                      </linearGradient>
                      <linearGradient id="neon-grad-cta" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="#fdcb6e" />
                        <stop offset="100%" stopColor="#ffeaa7" />
                      </linearGradient>
                    </defs>
                  </svg>

                  {/* 4维评分圆形刻度 */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                      gap: 20,
                      marginBottom: 24,
                    }}
                  >
                    {[
                      { key: "hook", label: "黄金3秒 Hook", score: diagnoseResult.hook_score, grad: "url(#neon-grad-hook)" },
                      { key: "conversion", label: "产品卖点说服力", score: diagnoseResult.conversion_score, grad: "url(#neon-grad-conversion)" },
                      { key: "fluency", label: "口播流畅度", score: diagnoseResult.fluency_score, grad: "url(#neon-grad-fluency)" },
                      { key: "cta", label: "行动号召引导力", score: diagnoseResult.cta_score, grad: "url(#neon-grad-cta)" },
                    ].map((d) => {
                      const circ = 2 * Math.PI * 34;
                      return (
                        <div
                          key={d.key}
                          className="glass-card"
                          style={{
                            padding: 16,
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "center",
                            background: "rgba(255,255,255,0.02)",
                          }}
                        >
                          <div style={{ position: "relative", width: 80, height: 80 }}>
                            <svg width="80" height="80" viewBox="0 0 80 80" style={{ transform: "rotate(-90deg)" }}>
                              <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="6" />
                              <circle
                                cx="40"
                                cy="40"
                                r="34"
                                fill="none"
                                stroke={d.grad}
                                strokeWidth="6"
                                strokeDasharray={circ}
                                strokeDashoffset={circ * (1 - d.score / 100)}
                                strokeLinecap="round"
                                style={{ transition: "stroke-dashoffset 0.8s ease-out" }}
                              />
                            </svg>
                            <div
                              style={{
                                position: "absolute",
                                top: 0,
                                left: 0,
                                right: 0,
                                bottom: 0,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                flexDirection: "column",
                              }}
                            >
                              <span style={{ fontSize: 18, fontWeight: 900, color: "var(--text-primary)" }}>{d.score}</span>
                              <span style={{ fontSize: 9, color: "var(--text-muted)", marginTop: -2 }}>分</span>
                            </div>
                          </div>
                          <span style={{ fontSize: 12, fontWeight: 700, marginTop: 12, color: "var(--text-secondary)", textAlign: "center" }}>
                            {d.label}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  {/* 详细评价色块 */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                    {[
                      { label: "🧲 首3秒Hook评价", score: diagnoseResult.hook_score, feedback: diagnoseResult.hook_feedback },
                      { label: "📈 转化说服力评价", score: diagnoseResult.conversion_score, feedback: diagnoseResult.conversion_feedback },
                      { label: "💬 口语化流畅评价", score: diagnoseResult.fluency_score, feedback: diagnoseResult.fluency_feedback },
                      { label: "📣 行动号召评价", score: diagnoseResult.cta_score, feedback: diagnoseResult.cta_feedback },
                    ].map((item, idx) => {
                      const getScoreColor = (s: number) => {
                        if (s >= 85) return { border: "rgba(0, 184, 148, 0.3)", bg: "rgba(0, 184, 148, 0.05)", text: "var(--success)" };
                        if (s >= 70) return { border: "rgba(253, 203, 110, 0.3)", bg: "rgba(253, 203, 110, 0.05)", text: "var(--warning)" };
                        return { border: "rgba(255, 107, 107, 0.3)", bg: "rgba(255, 107, 107, 0.05)", text: "var(--danger)" };
                      };
                      const st = getScoreColor(item.score);
                      return (
                        <div
                          key={idx}
                          style={{
                            padding: 16,
                            background: st.bg,
                            border: `1px solid ${st.border}`,
                            borderRadius: "var(--radius-md)",
                            display: "flex",
                            flexDirection: "column",
                            gap: 8,
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{item.label}</span>
                            <span style={{ fontSize: 11, fontWeight: 800, color: st.text, padding: "2px 8px", background: "rgba(255,255,255,0.03)", borderRadius: 10 }}>
                              {item.score >= 85 ? "优秀" : item.score >= 70 ? "良好" : "需优化"}
                            </span>
                          </div>
                          <p style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                            {item.feedback}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                marginBottom: 20,
              }}
            >
              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label">生成数量</label>
                <select
                  className="form-select"
                  value={variantCount}
                  onChange={(e) => setVariantCount(Number(e.target.value))}
                >
                  {[3, 5, 6, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      {n} 条
                    </option>
                  ))}
                </select>
              </div>
              <button
                className="btn btn-primary"
                onClick={handleGenerateVariants}
                disabled={loading}
                style={{ marginTop: 20 }}
              >
                {loading ? "⏳ 生成中..." : "🎯 生成变体"}
              </button>
            </div>

            {variants.length > 0 && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                {variants.map((v) => (
                  <div
                    key={v.variant_id}
                    onClick={() => {
                      const next = new Set(selectedVariants);
                      if (next.has(v.variant_id)) {
                        next.delete(v.variant_id);
                      } else {
                        next.add(v.variant_id);
                      }
                      setSelectedVariants(next);
                    }}
                    style={{
                      padding: 16,
                      background: selectedVariants.has(v.variant_id)
                        ? "rgba(108, 92, 231, 0.08)"
                        : "var(--bg-elevated)",
                      border: `1px solid ${
                        selectedVariants.has(v.variant_id)
                          ? "var(--accent-primary)"
                          : "var(--border-subtle)"
                      }`,
                      borderRadius: "var(--radius-md)",
                      cursor: "pointer",
                      transition: "all var(--transition-fast)",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: 8,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <input
                          type="checkbox"
                          checked={selectedVariants.has(v.variant_id)}
                          onChange={() => {}}
                          style={{ accentColor: "var(--accent-primary)" }}
                        />
                        <span
                          style={{
                            fontSize: 13,
                            fontWeight: 700,
                            color: "var(--accent-secondary)",
                          }}
                        >
                          {v.style}
                        </span>
                      </div>
                      <span
                        style={{
                          fontSize: 12,
                          color: "var(--text-muted)",
                        }}
                      >
                        ~{v.estimated_duration.toFixed(0)}秒
                      </span>
                    </div>
                    <p
                      style={{
                        fontSize: 13,
                        color: "var(--text-secondary)",
                        lineHeight: 1.7,
                      }}
                    >
                      {v.full_script}
                    </p>
                  </div>
                ))}
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--text-muted)",
                    textAlign: "right",
                  }}
                >
                  已选择 {selectedVariants.size}/{variants.length} 条
                </div>
              </div>
            )}
          </div>
        )}

        {/* ───── Step 5: 配置 ───── */}
        {step === "config" && (
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 24 }}>
              ⚙️ 生成配置
            </h2>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 20,
              }}
            >
              <div className="form-group">
                <label className="form-label">视频比例</label>
                <select
                  className="form-select"
                  value={videoAspect}
                  onChange={(e) => setVideoAspect(e.target.value)}
                >
                  <option value="9:16">竖屏 9:16（抖音推荐）</option>
                  <option value="16:9">横屏 16:9</option>
                  <option value="1:1">方形 1:1</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">并发数</label>
                <select
                  className="form-select"
                  value={maxConcurrent}
                  onChange={(e) => setMaxConcurrent(Number(e.target.value))}
                >
                  {[1, 2, 3, 5].map((n) => (
                    <option key={n} value={n}>
                      {n} 并发
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">字幕</label>
                <div style={{ display: "flex", alignItems: "center", gap: 8, paddingTop: 8 }}>
                  <input
                    type="checkbox"
                    checked={subtitleEnabled}
                    onChange={(e) => setSubtitleEnabled(e.target.checked)}
                    style={{ accentColor: "var(--accent-primary)" }}
                  />
                  <span style={{ fontSize: 14 }}>启用字幕</span>
                </div>
              </div>

              {/* 平移镜头动效张力 */}
              <div className="form-group" style={{ gridColumn: "span 2", marginTop: 8 }}>
                <label className="form-label" style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>平移镜头动效张力 (Ken Burns Scale)</span>
                  <span style={{ color: "var(--accent-secondary)", fontWeight: 700 }}>{motionIntensity.toFixed(1)}x</span>
                </label>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <input
                    type="range"
                    min="0.0"
                    max="1.5"
                    step="0.1"
                    value={motionIntensity}
                    onChange={(e) => setMotionIntensity(parseFloat(e.target.value))}
                    style={{ flex: 1, accentColor: "var(--accent-primary)" }}
                  />
                  <span style={{ fontSize: 12, color: "var(--text-muted)", width: 40 }}>0.0 - 1.5</span>
                </div>
              </div>

              {/* 抖音透明浮动价格牌 */}
              <div className="form-group" style={{ gridColumn: "span 2", marginTop: 12 }}>
                <label className="form-label" style={{ color: "var(--accent-secondary)", fontSize: 14 }}>🏷️ 抖音透明浮动价格牌 & 倒计时 (Remotion CTA)</label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 8 }}>
                  <div className="form-group">
                    <label className="form-label" style={{ fontSize: 11 }}>秒杀促销价</label>
                    <input
                      className="form-input"
                      placeholder="如：89.9"
                      value={ctaPrice}
                      onChange={(e) => setCtaPrice(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label" style={{ fontSize: 11 }}>商品原价</label>
                    <input
                      className="form-input"
                      placeholder="如：299.0"
                      value={ctaOriginalPrice}
                      onChange={(e) => setCtaOriginalPrice(e.target.value)}
                    />
                  </div>
                </div>
                <div className="form-group" style={{ marginTop: 12 }}>
                  <label className="form-label" style={{ fontSize: 11 }}>底部 CTA 引导语（未填时默认使用口播结尾）</label>
                  <input
                    className="form-input"
                    placeholder="如：点击下方链接，立即抢购！"
                    value={ctaText}
                    onChange={(e) => setCtaText(e.target.value)}
                  />
                </div>
              </div>

              {/* Webhook 回调 */}
              <div className="form-group" style={{ gridColumn: "span 2", marginTop: 12 }}>
                <label className="form-label" style={{ color: "var(--info)", fontSize: 14 }}>🔗 Webhook 回调分发生态</label>
                <div style={{ marginTop: 8 }}>
                  <input
                    className="form-input"
                    placeholder="请输入 Webhook URL（如：https://yourdomain.com/api/video-webhook）"
                    value={webhookUrl}
                    onChange={(e) => setWebhookUrl(e.target.value)}
                    style={{ width: "100%" }}
                  />
                  <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
                    当批量视频合成完毕后，系统将自动将高清视频包、SRT 字幕及口播文本推送到该地址。
                  </p>
                </div>
              </div>
            </div>

            <div
              style={{
                marginTop: 32,
                padding: 20,
                background: "var(--bg-elevated)",
                borderRadius: "var(--radius-md)",
                fontSize: 13,
                color: "var(--text-secondary)",
                lineHeight: 1.8,
              }}
            >
              <strong style={{ color: "var(--text-primary)" }}>📊 任务预览</strong>
              <br />
              产品：{productName}
              <br />
              视频数量：{selectedVariants.size} 条
              <br />
              比例：{videoAspect}
              <br />
              并发：{maxConcurrent}
              <br />
              镜头张力：{motionIntensity.toFixed(1)}x
              <br />
              字幕：{subtitleEnabled ? "启用" : "关闭"}
              {ctaPrice && (
                <>
                  <br />
                  秒杀价：¥{ctaPrice} (原价: ¥{ctaOriginalPrice || "无"})
                </>
              )}
              {webhookUrl && (
                <>
                  <br />
                  Webhook：{webhookUrl}
                </>
              )}
            </div>
          </div>
        )}

        {/* ───── Step 6: 提交成功 ───── */}
        {step === "submit" && batchId && (
          <div style={{ textAlign: "center", padding: 32 }}>
            <div style={{ fontSize: 64, marginBottom: 16 }}>🎉</div>
            <h2
              style={{
                fontSize: 24,
                fontWeight: 800,
                marginBottom: 12,
              }}
            >
              任务已提交！
            </h2>
            <p
              style={{
                color: "var(--text-secondary)",
                fontSize: 15,
                marginBottom: 32,
              }}
            >
              批量 ID：{batchId}
              <br />
              {selectedVariants.size} 条视频正在生成中
            </p>
            <div style={{ display: "flex", justifyContent: "center", gap: 16 }}>
              <a
                href={`/batch?id=${batchId}`}
                className="btn btn-primary"
              >
                📊 查看进度
              </a>
              <a href="/" className="btn btn-secondary">
                返回首页
              </a>
            </div>
          </div>
        )}
      </div>

      {/* ── 底部导航 ── */}
      {step !== "submit" && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <button
            className="btn btn-ghost"
            onClick={goPrev}
            disabled={currentIdx === 0}
          >
            ← 上一步
          </button>

          {step === "config" ? (
            <button
              className="btn btn-primary"
              onClick={handleSubmit}
              disabled={loading}
              style={{ padding: "14px 36px" }}
            >
              {loading ? "⏳ 提交中..." : "🚀 提交批量生成"}
            </button>
          ) : (
            <button
              className="btn btn-primary"
              onClick={goNext}
              disabled={!canGoNext()}
            >
              下一步 →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
