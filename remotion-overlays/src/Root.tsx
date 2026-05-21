import React from "react";
import { Composition } from "remotion";
import { CTAOverlay } from "./compositions/CTAOverlay";
import { PriceTag } from "./compositions/PriceTag";

/**
 * Remotion Root — 注册所有可渲染的 Composition。
 *
 * 每个 Composition 可以通过 CLI 指定 `--composition` 来渲染。
 * inputProps 通过 `--props` JSON 传入。
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* CTA 叠层 — 默认 3 秒 (90 帧@30fps) */}
      <Composition
        id="CTAOverlay"
        component={CTAOverlay}
        durationInFrames={90}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          text: "点击关注，今晚8点直播间见！",
          subText: "限时福利 手慢无",
          animationStyle: "slide-up" as const,
          bgColor: "rgba(255, 50, 80, 0.95)",
          textColor: "#FFFFFF",
          fontSize: 48,
          borderRadius: 16,
        }}
      />

      {/* 价格标签 — 默认 4 秒 (120 帧@30fps) */}
      <Composition
        id="PriceTag"
        component={PriceTag}
        durationInFrames={120}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          currentPrice: "99",
          originalPrice: "299",
          discount: "限时3折",
          position: "top-right" as const,
          animationStyle: "bounce" as const,
        }}
      />
    </>
  );
};
