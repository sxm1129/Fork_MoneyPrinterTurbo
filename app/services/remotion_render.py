"""
Remotion 渲染桥接模块。

提供 Python 侧调用 Remotion CLI 渲染 CTA/PriceTag 叠层的接口。
渲染输出透明通道 WebM，后续通过 ffmpeg 合成到主视频。
"""

import json
import os
import subprocess
from typing import Optional

from loguru import logger

from app.config import config
from app.services.video import get_ffmpeg_binary


# ────────────────────────── 配置 ──────────────────────────

def _get_remotion_dir() -> str:
    """获取 Remotion 项目目录。"""
    promo_cfg = config._cfg.get("promo", {})
    custom_dir = promo_cfg.get("remotion_project_dir", "")
    if custom_dir and os.path.isdir(custom_dir):
        return custom_dir

    # 默认在项目根目录下
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    return os.path.join(root_dir, "remotion-overlays")


def is_remotion_available() -> bool:
    """检查 Remotion 是否可用。"""
    promo_cfg = config._cfg.get("promo", {})
    if not promo_cfg.get("remotion_enabled", False):
        return False

    remotion_dir = _get_remotion_dir()
    return os.path.isdir(remotion_dir) and os.path.isfile(
        os.path.join(remotion_dir, "package.json")
    )


# ────────────────────────── 渲染接口 ──────────────────────────

def render_cta_overlay(
    output_path: str,
    text: str,
    sub_text: str = "",
    animation_style: str = "slide-up",
    bg_color: str = "rgba(255, 50, 80, 0.95)",
    text_color: str = "#FFFFFF",
    font_size: int = 48,
    duration_frames: int = 90,
    width: int = 1080,
    height: int = 1920,
) -> Optional[str]:
    """
    渲染 CTA 叠层视频（带透明通道）。

    Args:
        output_path: 输出视频路径 (.webm)
        text: CTA 文字
        sub_text: 副标题
        animation_style: 动画风格
        bg_color: 背景色
        text_color: 文字色
        font_size: 字号
        duration_frames: 总帧数 (默认 90 帧 = 3 秒@30fps)
        width: 宽度
        height: 高度

    Returns:
        输出文件路径，失败返回 None
    """
    props = {
        "text": text,
        "subText": sub_text,
        "animationStyle": animation_style,
        "bgColor": bg_color,
        "textColor": text_color,
        "fontSize": font_size,
        "borderRadius": 16,
    }

    return _render_composition(
        composition_id="CTAOverlay",
        output_path=output_path,
        props=props,
        duration_frames=duration_frames,
        width=width,
        height=height,
    )


def render_price_tag(
    output_path: str,
    current_price: str,
    original_price: str = "",
    discount: str = "",
    position: str = "top-right",
    animation_style: str = "bounce",
    duration_frames: int = 120,
    width: int = 1080,
    height: int = 1920,
) -> Optional[str]:
    """
    渲染价格标签叠层视频（带透明通道）。

    Args:
        output_path: 输出视频路径 (.webm)
        current_price: 现价
        original_price: 原价
        discount: 折扣文字
        position: 位置
        animation_style: 动画风格
        duration_frames: 总帧数
        width: 宽度
        height: 高度

    Returns:
        输出文件路径，失败返回 None
    """
    props = {
        "currentPrice": current_price,
        "originalPrice": original_price,
        "discount": discount,
        "position": position,
        "animationStyle": animation_style,
    }

    return _render_composition(
        composition_id="PriceTag",
        output_path=output_path,
        props=props,
        duration_frames=duration_frames,
        width=width,
        height=height,
    )


# ────────────────────────── 合成接口 ──────────────────────────

def composite_overlay(
    base_video: str,
    overlay_video: str,
    output_path: str,
    start_time: float = 0,
) -> Optional[str]:
    """
    将透明叠层视频合成到基础视频上。

    使用 ffmpeg overlay 滤镜，叠层从 start_time 开始播放。

    Args:
        base_video: 基础视频路径
        overlay_video: 叠层视频路径 (.webm 带 alpha)
        output_path: 输出路径
        start_time: 叠层开始时间（秒）

    Returns:
        输出路径，失败返回 None
    """
    ffmpeg_bin = get_ffmpeg_binary()

    cmd = [
        ffmpeg_bin, "-y",
        "-i", base_video,
        "-i", overlay_video,
        "-filter_complex",
        f"[1:v]setpts=PTS+{start_time}/TB[ov];[0:v][ov]overlay=0:0:enable='between(t,{start_time},{start_time}+10)':shortest=1",
        "-c:v", "libx264",
        "-c:a", "copy",
        "-shortest",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"Overlay composite done: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Overlay composite failed: {e.stderr[:500]}")
        return None


# ────────────────────────── 内部渲染函数 ──────────────────────────

def _render_composition(
    composition_id: str,
    output_path: str,
    props: dict,
    duration_frames: int = 90,
    width: int = 1080,
    height: int = 1920,
) -> Optional[str]:
    """
    调用 Remotion CLI 渲染指定 Composition。
    """
    remotion_dir = _get_remotion_dir()

    if not os.path.isdir(remotion_dir):
        logger.error(f"Remotion project not found: {remotion_dir}")
        return None

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 写入 props 临时文件
    props_file = output_path + ".props.json"
    with open(props_file, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        composition_id,
        output_path,
        "--props", props_file,
        "--codec", "vp8",  # WebM with alpha
        "--pixel-format", "yuva420p",
        "--image-format", "png",
        "--width", str(width),
        "--height", str(height),
        "--frames", f"0-{duration_frames - 1}",
    ]

    try:
        logger.info(f"Rendering {composition_id} → {output_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=remotion_dir,
            timeout=120,  # 2 分钟超时
        )

        if result.returncode != 0:
            logger.error(f"Remotion render failed: {result.stderr[:500]}")
            return None

        logger.success(f"Remotion render complete: {output_path}")
        return output_path

    except subprocess.TimeoutExpired:
        logger.error(f"Remotion render timed out for {composition_id}")
        return None
    except Exception as e:
        logger.error(f"Remotion render error: {e}")
        return None
    finally:
        # 清理 props 临时文件
        if os.path.exists(props_file):
            os.remove(props_file)
