import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/**
 * PriceTag — 价格标签叠层组件
 *
 * 用于展示产品价格、折扣信息。
 * 支持原价划线 + 现价高亮的常见电商样式。
 */

interface PriceTagProps {
  currentPrice: string;
  originalPrice?: string;
  discount?: string;
  position?: "top-right" | "top-left" | "bottom-right" | "bottom-left";
  animationStyle?: "bounce" | "slide" | "rotate";
}

export const PriceTag: React.FC<PriceTagProps> = ({
  currentPrice,
  originalPrice = "",
  discount = "",
  position = "top-right",
  animationStyle = "bounce",
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const enterProgress = spring({
    frame,
    fps,
    config: { damping: 10, stiffness: 200, mass: 0.6 },
  });

  // 退场
  const exitStart = durationInFrames - 8;
  const exitOpacity =
    frame >= exitStart
      ? interpolate(frame, [exitStart, durationInFrames], [1, 0], {
          extrapolateRight: "clamp",
        })
      : 1;

  const opacity = enterProgress * exitOpacity;

  let transform = "";
  switch (animationStyle) {
    case "bounce":
      const scale = interpolate(enterProgress, [0, 1], [0.1, 1]);
      transform = `scale(${scale})`;
      break;
    case "slide":
      const tx = interpolate(enterProgress, [0, 1], [200, 0]);
      transform = `translateX(${tx}px)`;
      break;
    case "rotate":
      const rotate = interpolate(enterProgress, [0, 1], [-15, 0]);
      const s = interpolate(enterProgress, [0, 1], [0.5, 1]);
      transform = `rotate(${rotate}deg) scale(${s})`;
      break;
  }

  // 位置映射
  const positionStyle: React.CSSProperties = {
    position: "absolute",
  };

  switch (position) {
    case "top-right":
      positionStyle.top = 60;
      positionStyle.right = 40;
      break;
    case "top-left":
      positionStyle.top = 60;
      positionStyle.left = 40;
      break;
    case "bottom-right":
      positionStyle.bottom = 160;
      positionStyle.right = 40;
      break;
    case "bottom-left":
      positionStyle.bottom = 160;
      positionStyle.left = 40;
      break;
  }

  // 价格脉冲
  const pulse = interpolate(Math.sin(frame * 0.12), [-1, 1], [1, 1.05]);

  return (
    <AbsoluteFill>
      <div
        style={{
          ...positionStyle,
          opacity,
          transform: `${transform} scale(${pulse})`,
          transformOrigin: "center center",
        }}
      >
        {/* 折扣角标 */}
        {discount && (
          <div
            style={{
              position: "absolute",
              top: -14,
              right: -14,
              background: "linear-gradient(135deg, #FF6B35, #FF2E63)",
              color: "#fff",
              fontSize: 22,
              fontWeight: 800,
              padding: "6px 14px",
              borderRadius: 20,
              boxShadow: "0 2px 10px rgba(255,46,99,0.5)",
              zIndex: 2,
            }}
          >
            {discount}
          </div>
        )}

        {/* 主价格卡片 */}
        <div
          style={{
            background: "linear-gradient(145deg, #1a1a2e, #16213e)",
            border: "2px solid rgba(255,255,255,0.15)",
            borderRadius: 16,
            padding: "18px 28px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 6,
            boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
            backdropFilter: "blur(8px)",
          }}
        >
          {/* 原价 */}
          {originalPrice && (
            <div
              style={{
                color: "rgba(255,255,255,0.5)",
                fontSize: 24,
                textDecoration: "line-through",
                fontWeight: 500,
              }}
            >
              ¥{originalPrice}
            </div>
          )}

          {/* 现价 */}
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 4,
            }}
          >
            <span
              style={{
                color: "#FF2E63",
                fontSize: 28,
                fontWeight: 700,
              }}
            >
              ¥
            </span>
            <span
              style={{
                background: "linear-gradient(to right, #FF2E63, #FF6B35)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                fontSize: 56,
                fontWeight: 900,
                letterSpacing: -2,
              }}
            >
              {currentPrice}
            </span>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
