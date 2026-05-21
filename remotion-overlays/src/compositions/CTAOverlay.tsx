import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/**
 * CTAOverlay — "行动号召" 叠层组件
 *
 * 在视频末尾 3-5 秒弹出，支持多种动画风格：
 * - slide-up: 从底部滑入
 * - scale: 缩放弹出
 * - fade: 淡入
 *
 * 输出带透明背景的视频，后续用 ffmpeg alpha 通道合成到主视频上。
 */

interface CTAOverlayProps {
  text: string;
  subText?: string;
  animationStyle?: "slide-up" | "scale" | "fade";
  bgColor?: string;
  textColor?: string;
  fontSize?: number;
  borderRadius?: number;
}

export const CTAOverlay: React.FC<CTAOverlayProps> = ({
  text,
  subText = "",
  animationStyle = "slide-up",
  bgColor = "rgba(255, 50, 80, 0.95)",
  textColor = "#FFFFFF",
  fontSize = 48,
  borderRadius = 16,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // 入场动画 (前 15 帧)
  const enterProgress = spring({
    frame,
    fps,
    config: { damping: 12, stiffness: 150, mass: 0.8 },
  });

  // 退场动画 (最后 10 帧)
  const exitStart = durationInFrames - 10;
  const exitProgress =
    frame >= exitStart
      ? interpolate(frame, [exitStart, durationInFrames], [1, 0], {
          extrapolateRight: "clamp",
        })
      : 1;

  const opacity = enterProgress * exitProgress;

  let transform = "";

  switch (animationStyle) {
    case "slide-up":
      const translateY = interpolate(enterProgress, [0, 1], [120, 0]);
      transform = `translateY(${translateY}px)`;
      break;
    case "scale":
      const scale = interpolate(enterProgress, [0, 1], [0.3, 1]);
      transform = `scale(${scale})`;
      break;
    case "fade":
    default:
      break;
  }

  // 呼吸光效动画
  const glowIntensity = interpolate(
    Math.sin(frame * 0.15),
    [-1, 1],
    [0, 12]
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: 80,
      }}
    >
      <div
        style={{
          opacity,
          transform,
          background: bgColor,
          padding: "20px 48px",
          borderRadius,
          boxShadow: `0 4px 24px rgba(0,0,0,0.3), 0 0 ${glowIntensity}px rgba(255,255,255,0.4)`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 8,
          maxWidth: "85%",
        }}
      >
        <div
          style={{
            color: textColor,
            fontSize,
            fontWeight: 800,
            textAlign: "center",
            lineHeight: 1.3,
            letterSpacing: 2,
            textShadow: "0 2px 8px rgba(0,0,0,0.3)",
          }}
        >
          {text}
        </div>
        {subText && (
          <div
            style={{
              color: textColor,
              fontSize: fontSize * 0.5,
              fontWeight: 500,
              opacity: 0.85,
              textAlign: "center",
            }}
          >
            {subText}
          </div>
        )}
        {/* 闪烁箭头 */}
        <div
          style={{
            marginTop: 4,
            fontSize: fontSize * 0.6,
            opacity: interpolate(Math.sin(frame * 0.2), [-1, 1], [0.4, 1]),
            color: textColor,
          }}
        >
          ▼
        </div>
      </div>
    </AbsoluteFill>
  );
};
