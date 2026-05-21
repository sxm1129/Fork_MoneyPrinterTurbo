"""
素材智能分析模块 — 负责用户上传素材的抽帧、场景切割、LLM 多模态分析。

处理流程：
  视频：ffmpeg 抽帧 → LLM 视觉理解 → 场景切割 → 带标签的片段列表
  图片：直接 LLM 视觉分析 → 带标签的图片信息
"""

import base64
import json
import os
import re
import subprocess
import shutil
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from loguru import logger

from app.config import config
from app.services import llm
from app.services.video import get_ffmpeg_binary
from app.utils import utils


# ────────────────────────── 数据结构 ──────────────────────────

@dataclass
class AnalyzedSegment:
    """分析后的素材片段。"""
    file_path: str                          # 片段文件路径
    segment_type: str = "image"             # "video_clip" | "image"
    start_time: float = 0.0                 # 视频片段起始时间
    end_time: float = 0.0                   # 视频片段结束时间
    content_tags: List[str] = field(default_factory=list)  # ["产品特写", "模特展示"]
    description: str = ""                   # "白色瓶身护肤品正面特写，背景简洁"
    quality_score: float = 0.0              # 0-100
    relevance_score: float = 0.0            # 0-100

    def to_dict(self):
        return asdict(self)


# ────────────────────────── 配置 ──────────────────────────

def _get_promo_config(key: str, default=None):
    """从 [promo] 配置区块读取参数。"""
    promo_cfg = config._cfg.get("promo", {})
    return promo_cfg.get(key, default)


# ────────────────────────── ffmpeg 工具函数 ──────────────────────────

def extract_keyframes(
    video_path: str,
    output_dir: str,
    interval: float = 2.0,
    max_frames: int = 30,
) -> List[str]:
    """
    用 ffmpeg 按固定时间间隔从视频中抽取关键帧。

    Args:
        video_path: 视频文件路径
        output_dir: 帧图片输出目录
        interval: 抽帧间隔（秒）
        max_frames: 最大抽帧数

    Returns:
        帧图片路径列表
    """
    os.makedirs(output_dir, exist_ok=True)
    ffmpeg_bin = get_ffmpeg_binary()

    # 先获取视频时长
    probe_cmd = [
        ffmpeg_bin, "-i", video_path,
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-i", video_path],
            capture_output=True, text=True, check=False
        )
        stderr = result.stderr
        # 从 ffmpeg 输出中提取时长
        duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', stderr)
        if duration_match:
            h, m, s = duration_match.groups()
            total_duration = int(h) * 3600 + int(m) * 60 + float(s)
        else:
            total_duration = 60.0  # 默认 60 秒
    except Exception:
        total_duration = 60.0

    # 计算实际抽帧数
    frame_count = min(int(total_duration / interval), max_frames)
    frame_count = max(frame_count, 1)

    logger.info(
        f"Extracting keyframes: video={os.path.basename(video_path)}, "
        f"duration={total_duration:.1f}s, interval={interval}s, "
        f"frames={frame_count}"
    )

    # 使用 fps 滤镜按间隔抽帧
    output_pattern = os.path.join(output_dir, "frame_%04d.png")
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-frames:v", str(frame_count),
        "-q:v", "2",
        output_pattern,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            logger.error(f"ffmpeg keyframe extraction failed: {result.stderr[:500]}")
            return []
    except Exception as e:
        logger.error(f"ffmpeg keyframe extraction error: {e}")
        return []

    # 收集输出帧文件
    frames = sorted([
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.startswith("frame_") and f.endswith(".png")
    ])

    logger.info(f"Extracted {len(frames)} keyframes")
    return frames


def split_video_by_scenes(
    video_path: str,
    output_dir: str,
    threshold: float = 0.3,
) -> List[dict]:
    """
    用 ffmpeg 场景检测滤镜切割视频为多个片段。

    Args:
        video_path: 视频文件路径
        output_dir: 片段输出目录
        threshold: 场景变化检测阈值 (0-1, 越小越敏感)

    Returns:
        片段信息列表 [{"file_path": ..., "start_time": ..., "end_time": ...}]
    """
    os.makedirs(output_dir, exist_ok=True)
    ffmpeg_bin = get_ffmpeg_binary()

    # 使用 scene detect 获取切割点
    cmd = [
        ffmpeg_bin,
        "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        stderr = result.stderr

        # 解析场景切换时间点
        scene_times = [0.0]
        for match in re.finditer(r'pts_time:(\d+\.?\d*)', stderr):
            time_val = float(match.group(1))
            if time_val - scene_times[-1] > 1.0:  # 至少间隔 1 秒
                scene_times.append(time_val)

        # 获取总时长
        duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', stderr)
        if duration_match:
            h, m, s = duration_match.groups()
            total_duration = int(h) * 3600 + int(m) * 60 + float(s)
        else:
            total_duration = 60.0
        scene_times.append(total_duration)

    except Exception as e:
        logger.error(f"Scene detection failed: {e}")
        # 降级为等间隔切割
        total_duration = 60.0
        scene_times = list(range(0, int(total_duration), 5)) + [total_duration]

    # 切割视频片段
    segments = []
    for i in range(len(scene_times) - 1):
        start = scene_times[i]
        end = scene_times[i + 1]
        if end - start < 1.0:
            continue  # 跳过过短片段

        clip_path = os.path.join(output_dir, f"clip_{i+1:03d}.mp4")
        cmd = [
            ffmpeg_bin, "-y",
            "-i", video_path,
            "-ss", str(start),
            "-to", str(end),
            "-c:v", "libx264",
            "-an",  # 去除音频
            clip_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            segments.append({
                "file_path": clip_path,
                "start_time": start,
                "end_time": end,
            })
        except Exception as e:
            logger.warning(f"Failed to cut clip {i+1}: {e}")

    logger.info(f"Split video into {len(segments)} scene clips")
    return segments


# ────────────────────────── LLM 多模态分析 ──────────────────────────

def _image_to_base64(image_path: str) -> str:
    """将图片编码为 base64 字符串。"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _get_image_media_type(image_path: str) -> str:
    """根据扩展名获取图片 MIME 类型。"""
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return mime_map.get(ext, "image/png")


def analyze_frames_with_llm(
    frame_paths: List[str],
    product_context: str = "",
    batch_size: int = 4,
) -> List[dict]:
    """
    调用 LLM 多模态接口分析关键帧内容和质量。

    将帧分批发送给 LLM，每批分析 batch_size 张帧。

    Args:
        frame_paths: 帧图片路径列表
        product_context: 产品上下文描述
        batch_size: 每批分析的帧数

    Returns:
        分析结果列表 [{"frame_index": ..., "content_tags": [...], "description": ..., "quality_score": ..., "relevance_score": ...}]
    """
    import openai

    api_key = config.app.get("openai_api_key", "")
    base_url = config.app.get("openai_base_url", "")

    # 使用分析专用模型或回退到通用模型
    promo_cfg = config._cfg.get("promo", {})
    analysis_model = promo_cfg.get("analysis_model", "") or config.app.get("openai_model_name", "")

    if not api_key or not base_url:
        logger.warning("OpenAI API not configured, skipping frame analysis")
        return _generate_default_analysis(frame_paths)

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    all_results = []

    for batch_start in range(0, len(frame_paths), batch_size):
        batch = frame_paths[batch_start:batch_start + batch_size]
        logger.info(f"Analyzing frames {batch_start+1}-{batch_start+len(batch)}/{len(frame_paths)}")

        # 构建多模态消息
        content = [
            {
                "type": "text",
                "text": f"""分析以下 {len(batch)} 张视频关键帧图片。
产品/上下文：{product_context or '未提供'}

对每张图片，请返回 JSON 数组，包含以下字段：
- frame_index: 图片序号（从 {batch_start+1} 开始）
- content_tags: 内容标签数组（如 "产品特写", "模特展示", "使用效果", "包装展示", "生活场景", "品牌 logo"）
- description: 简短中文描述（20字以内）
- quality_score: 画面质量评分 0-100（清晰度、构图、色彩）
- relevance_score: 与产品的相关性评分 0-100

只返回 JSON 数组，不要其他内容。"""
            }
        ]

        for i, frame_path in enumerate(batch):
            try:
                b64 = _image_to_base64(frame_path)
                media_type = _get_image_media_type(frame_path)
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{b64}"
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to encode frame {frame_path}: {e}")

        try:
            response = client.chat.completions.create(
                model=analysis_model,
                messages=[{"role": "user", "content": content}],
                temperature=0.3,
                max_tokens=2000,
            )
            result_text = response.choices[0].message.content

            # 解析 JSON
            cleaned = re.sub(r"```(?:json)?\s*", "", result_text).strip()
            match = re.search(r'\[[\s\S]*\]', cleaned)
            if match:
                batch_results = json.loads(match.group(0))
                all_results.extend(batch_results)
            else:
                logger.warning(f"Failed to parse frame analysis response")
                all_results.extend(_generate_default_analysis(batch, offset=batch_start))

        except Exception as e:
            logger.error(f"LLM frame analysis failed: {e}")
            all_results.extend(_generate_default_analysis(batch, offset=batch_start))

    return all_results


def _generate_default_analysis(
    frame_paths: List[str],
    offset: int = 0,
) -> List[dict]:
    """当 LLM 分析不可用时，生成默认的分析结果。"""
    results = []
    for i, path in enumerate(frame_paths):
        results.append({
            "frame_index": offset + i + 1,
            "content_tags": ["待分析"],
            "description": f"视频帧 {offset + i + 1}",
            "quality_score": 50.0,
            "relevance_score": 50.0,
        })
    return results


# ────────────────────────── 统一入口 ──────────────────────────

def analyze_uploaded_material(
    file_path: str,
    product_context: str = "",
    task_id: str = "",
) -> List[AnalyzedSegment]:
    """
    分析用户上传的素材文件（视频或图片）。

    Args:
        file_path: 素材文件路径
        product_context: 产品上下文描述
        task_id: 任务 ID（用于创建工作目录）

    Returns:
        AnalyzedSegment 列表
    """
    if not os.path.exists(file_path):
        logger.error(f"Material file not found: {file_path}")
        return []

    ext = os.path.splitext(file_path)[1].lower()
    is_video = ext in (".mp4", ".mov", ".avi", ".flv", ".mkv", ".webm")
    is_image = ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

    if not is_video and not is_image:
        logger.error(f"Unsupported file format: {ext}")
        return []

    # 创建分析工作目录
    work_dir = os.path.join(
        utils.task_dir(task_id) if task_id else utils.storage_dir("temp_analysis"),
        "analysis"
    )
    os.makedirs(work_dir, exist_ok=True)

    promo_cfg = config._cfg.get("promo", {})
    keyframe_interval = promo_cfg.get("keyframe_interval", 2.0)
    max_frames = promo_cfg.get("max_analyzed_frames", 30)
    min_quality = promo_cfg.get("min_quality_score", 50)

    segments = []

    if is_image:
        # 图片直接分析
        logger.info(f"Analyzing image: {os.path.basename(file_path)}")
        results = analyze_frames_with_llm(
            frame_paths=[file_path],
            product_context=product_context,
        )
        if results:
            r = results[0]
            segments.append(AnalyzedSegment(
                file_path=file_path,
                segment_type="image",
                content_tags=r.get("content_tags", []),
                description=r.get("description", ""),
                quality_score=r.get("quality_score", 50),
                relevance_score=r.get("relevance_score", 50),
            ))

    elif is_video:
        logger.info(f"Analyzing video: {os.path.basename(file_path)}")

        # Step 1: 抽取关键帧
        frames_dir = os.path.join(work_dir, "frames")
        frames = extract_keyframes(
            video_path=file_path,
            output_dir=frames_dir,
            interval=keyframe_interval,
            max_frames=max_frames,
        )

        # Step 2: LLM 分析关键帧
        frame_results = []
        if frames:
            frame_results = analyze_frames_with_llm(
                frame_paths=frames,
                product_context=product_context,
            )

        # Step 3: 场景切割
        clips_dir = os.path.join(work_dir, "clips")
        scene_clips = split_video_by_scenes(
            video_path=file_path,
            output_dir=clips_dir,
        )

        # Step 4: 关联帧分析结果到视频片段
        for clip in scene_clips:
            clip_start = clip["start_time"]
            clip_end = clip["end_time"]

            # 找出属于这个片段时间范围内的帧分析结果
            related_frames = [
                r for r in frame_results
                if clip_start <= (r.get("frame_index", 0) - 1) * keyframe_interval < clip_end
            ]

            # 合并标签和分数
            all_tags = []
            descriptions = []
            quality_scores = []
            relevance_scores = []

            for r in related_frames:
                all_tags.extend(r.get("content_tags", []))
                descriptions.append(r.get("description", ""))
                quality_scores.append(r.get("quality_score", 50))
                relevance_scores.append(r.get("relevance_score", 50))

            # 去重标签
            unique_tags = list(dict.fromkeys(all_tags))
            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 50.0
            avg_relevance = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 50.0

            if avg_quality >= min_quality:
                segments.append(AnalyzedSegment(
                    file_path=clip["file_path"],
                    segment_type="video_clip",
                    start_time=clip_start,
                    end_time=clip_end,
                    content_tags=unique_tags or ["未标注"],
                    description=" | ".join(descriptions[:2]) if descriptions else "视频片段",
                    quality_score=avg_quality,
                    relevance_score=avg_relevance,
                ))

        # 如果没有场景切割结果，整体作为一个片段
        if not segments:
            overall_tags = []
            overall_quality = 50.0
            for r in frame_results:
                overall_tags.extend(r.get("content_tags", []))
            if frame_results:
                overall_quality = sum(
                    r.get("quality_score", 50) for r in frame_results
                ) / len(frame_results)

            segments.append(AnalyzedSegment(
                file_path=file_path,
                segment_type="video_clip",
                start_time=0.0,
                end_time=0.0,
                content_tags=list(dict.fromkeys(overall_tags)) or ["完整视频"],
                description="完整素材视频",
                quality_score=overall_quality,
                relevance_score=50.0,
            ))

    logger.success(
        f"Material analysis complete: {len(segments)} segments, "
        f"file={os.path.basename(file_path)}"
    )
    return segments


def analyze_multiple_materials(
    file_paths: List[str],
    product_context: str = "",
    task_id: str = "",
) -> List[AnalyzedSegment]:
    """
    分析多个用户上传素材文件。

    Args:
        file_paths: 素材文件路径列表
        product_context: 产品上下文描述
        task_id: 任务 ID

    Returns:
        所有素材的 AnalyzedSegment 列表
    """
    all_segments = []
    for fp in file_paths:
        segments = analyze_uploaded_material(
            file_path=fp,
            product_context=product_context,
            task_id=task_id,
        )
        all_segments.extend(segments)

    logger.success(
        f"Analyzed {len(file_paths)} material files, "
        f"total segments: {len(all_segments)}"
    )
    return all_segments
