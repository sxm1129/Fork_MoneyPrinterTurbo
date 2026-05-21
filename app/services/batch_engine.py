"""
批量推广视频生成编排引擎。

管理批量任务的完整生命周期：
  素材分析 → 口播稿优化 → 风格变体生成 → 并行生成 N 条视频 → 汇总结果

采用两层状态模型：BatchState（整体）+ VideoState（每条视频）。
"""

import json
import math
import os
import random
import shutil
import traceback
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from enum import Enum
from os import path
from typing import List, Optional, Dict, Any

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import llm, material, video, voice, subtitle
from app.services import state as sm
from app.services.analyzer import AnalyzedSegment, analyze_multiple_materials
from app.services.script_engine import (
    ScriptVariant,
    ScriptSegment,
    optimize_script,
    generate_variants,
    plan_materials,
)
from app.utils import utils


# ────────────────────────── 两层状态枚举 ──────────────────────────

class BatchState(str, Enum):
    analyzing = "analyzing"
    scripting = "scripting"
    generating = "generating"
    completed = "completed"
    partial_failed = "partial_failed"
    failed = "failed"


class VideoState(str, Enum):
    queued = "queued"
    script_ready = "script_ready"
    tts = "tts"
    material_fetch = "material"
    composing = "composing"
    completed = "completed"
    failed = "failed"


# ────────────────────────── 批量任务数据模型 ──────────────────────────

@dataclass
class VideoTask:
    """单条视频的生成任务。"""
    video_id: str
    variant: dict                   # ScriptVariant.to_dict()
    voice_name: str = ""
    state: str = VideoState.queued.value
    progress: float = 0.0
    error: str = ""
    output_path: str = ""
    thumbnail_path: str = ""
    segment_video_paths: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class BatchTask:
    """批量任务的完整状态。"""
    batch_id: str
    state: str = BatchState.analyzing.value
    progress: float = 0.0

    # 输入
    product_name: str = ""
    product_description: str = ""
    livestream_purpose: str = ""
    raw_script: str = ""
    material_paths: List[str] = field(default_factory=list)

    # 中间结果
    optimized_script: str = ""
    analyzed_segments: List[dict] = field(default_factory=list)

    # 视频任务列表
    video_tasks: List[VideoTask] = field(default_factory=list)

    # 配置
    video_aspect: str = "9:16"
    video_clip_duration: int = 5
    subtitle_enabled: bool = True
    font_name: str = "STHeitiMedium.ttc"
    text_fore_color: str = "#FFFFFF"
    font_size: int = 60
    bgm_type: str = "random"
    bgm_file: str = ""
    cta_enabled: bool = True
    max_concurrent: int = 3
    motion_intensity: float = 1.0
    cta_config: Optional[dict] = None
    webhook_url: str = ""


    def to_dict(self):
        d = asdict(self)
        return d


# ────────────────────────── 全局批量任务存储 ──────────────────────────

_batch_tasks: Dict[str, BatchTask] = {}


def get_batch(batch_id: str) -> Optional[BatchTask]:
    return _batch_tasks.get(batch_id)


def get_batch_status(batch_id: str) -> Optional[dict]:
    batch = _batch_tasks.get(batch_id)
    if not batch:
        return None
    return batch.to_dict()


def list_batches() -> List[dict]:
    return [b.to_dict() for b in _batch_tasks.values()]


# ────────────────────────── 音色随机分配 ──────────────────────────

def _get_available_voices() -> List[str]:
    """获取所有可用的 TTS 音色。"""
    voices = []
    try:
        voices.extend(voice.get_openai_voices())
    except Exception:
        pass
    # 如果没有可用音色，使用默认
    if not voices:
        voices = ["openai:qwen3-tts-flash:alloy-Female"]
    return voices


def _assign_voices(count: int, voice_pool: Optional[List[str]] = None) -> List[str]:
    """为 N 条视频随机分配不同音色。"""
    if not voice_pool:
        voice_pool = _get_available_voices()

    assigned = []
    shuffled = voice_pool.copy()
    random.shuffle(shuffled)

    for i in range(count):
        assigned.append(shuffled[i % len(shuffled)])

    return assigned


# ────────────────────────── 批量任务工作目录 ──────────────────────────

def _batch_dir(batch_id: str) -> str:
    """获取或创建批量任务的工作目录。"""
    d = os.path.join(utils.task_dir(), batch_id)
    os.makedirs(d, exist_ok=True)
    return d


def _video_dir(batch_id: str, video_id: str) -> str:
    """获取或创建单条视频的工作目录。"""
    d = os.path.join(_batch_dir(batch_id), video_id)
    os.makedirs(d, exist_ok=True)
    return d


# ────────────────────────── 单条视频生成流水线 ──────────────────────────

def generate_single_video(
    batch_id: str,
    video_task: VideoTask,
    video_aspect: str = "9:16",
    video_clip_duration: int = 5,
    subtitle_enabled: bool = True,
    font_name: str = "STHeitiMedium.ttc",
    text_fore_color: str = "#FFFFFF",
    font_size: int = 60,
    bgm_type: str = "random",
    bgm_file: str = "",
    analyzed_segments: Optional[List[dict]] = None,
    cta_enabled: bool = True,
) -> dict:
    """
    单条视频的完整生成流水线。

    复用现有 task.py 中的核心函数来完成实际的视频合成。

    Returns:
        {"success": bool, "video_id": str, "output_path": str, "error": str}
    """
    video_id = video_task.video_id
    variant = video_task.variant
    voice_name = video_task.voice_name
    work_dir = _video_dir(batch_id, video_id)

    logger.info(f"[Batch {batch_id}] Starting video {video_id}, style='{variant.get('style', '')}'")

    try:
        # ─── Step 1: TTS 合成 ───
        video_task.state = VideoState.tts.value
        video_task.progress = 10
        _update_batch_video(batch_id, video_task)

        full_script = variant.get("full_script", "")
        if not full_script:
            raise ValueError("Empty script in variant")

        audio_file = os.path.join(work_dir, "audio.mp3")
        parsed_voice = voice.parse_voice_name(voice_name)
        logger.info(f"  [{video_id}] Synthesizing TTS with voice: {parsed_voice}")
        
        sub_maker = None
        try:
            sub_maker = voice.tts(
                text=full_script,
                voice_name=parsed_voice,
                voice_rate=1.0,
                voice_file=audio_file,
            )
        except Exception as e:
            logger.warning(f"  [{video_id}] Main TTS engine failed: {e}. Trying Edge TTS fallback...")

        if sub_maker is None or not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
            logger.warning(f"  [{video_id}] Main TTS failed for voice {voice_name}. Falling back to Edge TTS (zh-CN-XiaoxiaoNeural)...")
            fallback_voice = "zh-CN-XiaoxiaoNeural"
            try:
                sub_maker = voice.azure_tts_v1(
                    text=full_script,
                    voice_name=fallback_voice,
                    voice_rate=1.0,
                    voice_file=audio_file,
                )
            except Exception as fe:
                logger.error(f"  [{video_id}] Edge TTS fallback also failed: {fe}")
                sub_maker = None

        if sub_maker is None or not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
            raise RuntimeError(f"Both main TTS and Edge TTS fallback failed for voice {voice_name}")

        audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
        if audio_duration == 0:
            raise RuntimeError("Audio duration is 0")

        logger.info(f"  [{video_id}] TTS done: {audio_duration}s, voice={voice_name}")

        # ─── Step 2: 字幕生成 ───
        video_task.progress = 20
        _update_batch_video(batch_id, video_task)

        subtitle_path = ""
        if subtitle_enabled:
            subtitle_path = os.path.join(work_dir, "subtitle.srt")
            voice.create_subtitle(
                text=full_script,
                sub_maker=sub_maker,
                subtitle_file=subtitle_path,
            )
            if not os.path.exists(subtitle_path):
                logger.warning(f"  [{video_id}] Subtitle file not created, skipping")
                subtitle_path = ""

        # ─── Step 3: 获取视频素材 ───
        video_task.state = VideoState.material_fetch.value
        video_task.progress = 30
        _update_batch_video(batch_id, video_task)

        downloaded_videos = _fetch_materials_for_variant(
            variant=variant,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=video_clip_duration,
            analyzed_segments=analyzed_segments,
            work_dir=work_dir,
            batch_id=batch_id,
        )

        if not downloaded_videos:
            raise RuntimeError("No video materials obtained")

        video_task.segment_video_paths = downloaded_videos
        logger.info(f"  [{video_id}] Materials ready: {len(downloaded_videos)} clips")

        # ─── Step 4: 合成视频 ───
        video_task.state = VideoState.composing.value
        video_task.progress = 60
        _update_batch_video(batch_id, video_task)

        # 构建 VideoParams（复用现有合成逻辑）
        params = VideoParams(
            video_subject=variant.get("style", "推广视频"),
            video_aspect=VideoAspect(video_aspect),
            video_concat_mode=VideoConcatMode.random,
            video_transition_mode=VideoTransitionMode.shuffle,
            video_clip_duration=video_clip_duration,
            video_count=1,
            subtitle_enabled=subtitle_enabled,
            font_name=font_name,
            text_fore_color=text_fore_color,
            font_size=font_size,
            bgm_type=bgm_type,
            bgm_file=bgm_file,
            voice_name=voice_name,
            voice_rate=1.0,
        )

        combined_video_path = os.path.join(work_dir, "combined.mp4")
        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=params.video_concat_mode,
            video_transition_mode=params.video_transition_mode,
            max_clip_duration=params.video_clip_duration,
            threads=2,
        )

        video_task.progress = 80
        _update_batch_video(batch_id, video_task)

        final_video_path = os.path.join(work_dir, f"final-{video_id}.mp4")
        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
        )

        # ─── Step 4.5: Remotion CTA 叠层渲染与合成 ───
        if cta_enabled:
            from app.services import remotion_render
            if remotion_render.is_remotion_available():
                logger.info(f"  [{video_id}] Remotion is enabled and available, rendering CTA overlay...")
                batch = get_batch(batch_id)
                cta_config = batch.cta_config if batch else {}

                # 1. 底部 CTA 引导层
                cta_webm = os.path.join(work_dir, "cta_overlay.webm")
                cta_duration_sec = 3.0
                start_time = max(0.0, audio_duration - cta_duration_sec)
                cta_text = variant.get("cta_text", "点击下方链接，立即抢购！")
                if cta_config and cta_config.get("cta_text"):
                    cta_text = cta_config.get("cta_text")

                sub_text = "限时秒杀 • 抢完即止"
                if cta_config and cta_config.get("price"):
                    sub_text = f"限时秒杀价 ¥{cta_config.get('price')} • 抢完即止"

                rendered_cta = remotion_render.render_cta_overlay(
                    output_path=cta_webm,
                    text=cta_text,
                    sub_text=sub_text,
                    width=1080 if video_aspect == "9:16" else 1920,
                    height=1920 if video_aspect == "9:16" else 1080,
                )
                if rendered_cta and os.path.exists(rendered_cta):
                    overlayed_video_path = os.path.join(work_dir, f"overlayed-cta-{video_id}.mp4")
                    success_overlay = remotion_render.composite_overlay(
                        base_video=final_video_path,
                        overlay_video=rendered_cta,
                        output_path=overlayed_video_path,
                        start_time=start_time,
                    )
                    if success_overlay and os.path.exists(success_overlay):
                        final_video_path = overlayed_video_path

                # 2. 价格牌 CTA 标签
                if cta_config and cta_config.get("price"):
                    price_webm = os.path.join(work_dir, "price_tag.webm")
                    current_price = cta_config.get("price")
                    original_price = cta_config.get("original_price", "")
                    
                    discount = ""
                    if original_price:
                        try:
                            diff = float(original_price) - float(current_price)
                            if diff > 0:
                                discount = f"立减{int(diff)}元"
                        except Exception:
                            pass

                    rendered_price = remotion_render.render_price_tag(
                        output_path=price_webm,
                        current_price=current_price,
                        original_price=original_price,
                        discount=discount,
                        width=1080 if video_aspect == "9:16" else 1920,
                        height=1920 if video_aspect == "9:16" else 1080,
                    )
                    if rendered_price and os.path.exists(rendered_price):
                        overlayed_video_path = os.path.join(work_dir, f"overlayed-price-{video_id}.mp4")
                        success_overlay = remotion_render.composite_overlay(
                            base_video=final_video_path,
                            overlay_video=rendered_price,
                            output_path=overlayed_video_path,
                            start_time=0.5,
                        )
                        if success_overlay and os.path.exists(success_overlay):
                            logger.success(f"  [{video_id}] Remotion PriceTag overlay applied successfully!")
                            final_video_path = overlayed_video_path

        # ─── Step 5: 生成缩略图 ───
        thumbnail_path = os.path.join(work_dir, "thumbnail.jpg")
        _generate_thumbnail(final_video_path, thumbnail_path)

        # ─── 完成 ───
        video_task.state = VideoState.completed.value
        video_task.progress = 100
        video_task.output_path = final_video_path
        video_task.thumbnail_path = thumbnail_path
        _update_batch_video(batch_id, video_task)

        logger.success(f"  [{video_id}] Video generation complete: {final_video_path}")

        return {
            "success": True,
            "video_id": video_id,
            "output_path": final_video_path,
            "error": "",
        }

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"  [{video_id}] Video generation failed: {error_msg}")
        video_task.state = VideoState.failed.value
        video_task.error = str(e)
        _update_batch_video(batch_id, video_task)
        return {
            "success": False,
            "video_id": video_id,
            "output_path": "",
            "error": str(e),
        }


# ────────────────────────── 素材获取策略 ──────────────────────────

def _fetch_materials_for_variant(
    variant: dict,
    video_aspect: str,
    audio_duration: float,
    max_clip_duration: int,
    analyzed_segments: Optional[List[dict]] = None,
    work_dir: str = "",
    batch_id: str = "",
) -> List[str]:
    """
    根据变体的素材编排计划，混合获取素材。

    按 segment 级别获取不同类型的素材，最终返回视频素材路径列表。
    """
    segments = variant.get("segments", [])
    all_video_paths = []

    # 如果没有 segments（素材编排计划），使用默认的单一策略
    if not segments:
        # 降级为使用搜索词获取素材
        video_id = os.path.basename(work_dir)
        fallback_task_id = f"{batch_id}/{video_id}"
        video_source = config.app.get("video_source", "pexels")
        
        batch = get_batch(batch_id)
        product_name = batch.product_name if batch else "beauty product"
        
        if video_source == "flux-1-schnell":
            # flux 采用具体产品的高质量 Prompt
            search_terms = [
                f"A high-quality product photo of {product_name}, elegant lighting, 8k",
                f"Beautiful lifestyle demonstration of {product_name}, professional photography",
                f"A person using {product_name} in a daily scene, cinematic style, highly detailed"
            ]
        else:
            # Pexels / Pixabay 采用英文通用关键词以确保搜索有结果
            product_kw = product_name
            if any('\u4e00' <= char <= '\u9fff' for char in product_kw):
                product_kw = "skincare"
            search_terms = [product_kw, "beauty", "lifestyle"]

        video_paths = material.download_videos(
            task_id=fallback_task_id,
            search_terms=search_terms,
            source=video_source,
            video_aspect=VideoAspect(video_aspect),
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
        )
        return video_paths

    video_id = os.path.basename(work_dir)

    for i, seg in enumerate(segments):
        strategy = seg.get("material_strategy", "stock")
        ai_prompt = seg.get("ai_prompt", "")
        stock_keywords = seg.get("stock_keywords", [])
        user_path = seg.get("matched_user_segment_path", "")

        try:
            if strategy == "user_upload" and user_path and os.path.exists(user_path):
                # 直接使用用户上传的素材
                all_video_paths.append(user_path)

            elif strategy in ["ai_image", "ai_video"]:
                # AI 文生图 → MoviePy 转视频
                if ai_prompt:
                    # 使用基于 "batch_id/video_id/seg-{index}" 的唯一隔离标识
                    # 以彻底避免多视频变体、多自然段落并行运行时的图片和视频临时文件覆盖与冲突问题
                    seg_task_id = f"{batch_id}/{video_id}/seg-{i}"
                    image_paths = material.generate_images_flux(
                        task_id=seg_task_id,
                        search_terms=[ai_prompt],
                        audio_duration=max_clip_duration,
                        max_clip_duration=max_clip_duration,
                        video_aspect=VideoAspect(video_aspect),
                    )
                    if image_paths:
                        # 将图片转为视频
                        image_materials = []
                        for ip in image_paths:
                            item = MaterialInfo()
                            item.provider = "flux-1-schnell"
                            item.url = ip
                            item.duration = max_clip_duration
                            image_materials.append(item)
                        batch = get_batch(batch_id)
                        motion_intensity = batch.motion_intensity if batch else 1.0
                        processed = video.preprocess_video(
                            materials=image_materials,
                            clip_duration=max_clip_duration,
                            motion_intensity=motion_intensity,
                        )
                        for m in processed:
                            if m.url.endswith(".mp4"):
                                all_video_paths.append(m.url)

            elif strategy == "stock":
                # 从素材库搜索
                keywords = stock_keywords or ["product", "beauty"]
                for kw in keywords[:2]:  # 限制搜索次数
                    items = material.search_videos_pexels(
                        search_term=kw,
                        minimum_duration=max_clip_duration,
                        video_aspect=VideoAspect(video_aspect),
                    )
                    for item in items[:2]:
                        saved = material.save_video(video_url=item.url)
                        if saved:
                            all_video_paths.append(saved)
                    if all_video_paths:
                        break

        except Exception as e:
            logger.warning(
                f"Failed to fetch material for segment {i+1} "
                f"(strategy={strategy}): {e}"
            )

    # 如果没有获取到任何素材，降级到默认策略
    if not all_video_paths:
        logger.warning("No materials from segment plan, falling back to stock search")
        batch = get_batch(batch_id)
        product_name = batch.product_name if batch else "product"
        product_kw = product_name
        if any('\u4e00' <= char <= '\u9fff' for char in product_kw):
            product_kw = "skincare"
            
        search_terms = [product_kw, "beauty", "lifestyle"]
        
        fallback_task_id = f"{batch_id}/{video_id}"
        video_paths = material.download_videos(
            task_id=fallback_task_id,
            search_terms=search_terms,
            source="pexels",
            video_aspect=VideoAspect(video_aspect),
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
        )
        return video_paths

    return all_video_paths


# ────────────────────────── 辅助函数 ──────────────────────────

def _generate_thumbnail(video_path: str, output_path: str):
    """从视频第 1 秒截取缩略图。"""
    from app.services.video import get_ffmpeg_binary
    import subprocess

    try:
        cmd = [
            get_ffmpeg_binary(),
            "-y", "-i", video_path,
            "-ss", "1",
            "-vframes", "1",
            "-q:v", "2",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception as e:
        logger.warning(f"Failed to generate thumbnail: {e}")


def _update_batch_video(batch_id: str, video_task: VideoTask):
    """更新批量任务中某条视频的状态。"""
    batch = _batch_tasks.get(batch_id)
    if not batch:
        return

    for i, vt in enumerate(batch.video_tasks):
        if vt.video_id == video_task.video_id:
            batch.video_tasks[i] = video_task
            break

    # 更新整体进度
    if batch.video_tasks:
        total_progress = sum(vt.progress for vt in batch.video_tasks)
        batch.progress = total_progress / len(batch.video_tasks)


def _create_zip_archive(batch_id: str) -> str:
    """将批量任务的所有完成视频打包为 zip。"""
    batch = _batch_tasks.get(batch_id)
    if not batch:
        return ""

    zip_path = os.path.join(_batch_dir(batch_id), f"batch-{batch_id}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for vt in batch.video_tasks:
            if vt.state == VideoState.completed.value and vt.output_path:
                if os.path.exists(vt.output_path):
                    arcname = f"{vt.variant.get('style', vt.video_id)}-{vt.video_id}.mp4"
                    zf.write(vt.output_path, arcname)

    logger.info(f"Created zip archive: {zip_path}")
    return zip_path


# ────────────────────────── 批量任务入口 ──────────────────────────

def create_batch(
    product_name: str,
    raw_script: str = "",
    product_description: str = "",
    livestream_purpose: str = "",
    material_paths: Optional[List[str]] = None,
    video_aspect: str = "9:16",
    video_clip_duration: int = 5,
    subtitle_enabled: bool = True,
    font_name: str = "STHeitiMedium.ttc",
    text_fore_color: str = "#FFFFFF",
    font_size: int = 60,
    bgm_type: str = "random",
    bgm_file: str = "",
    cta_enabled: bool = True,
    max_concurrent: int = 3,
    motion_intensity: float = 1.0,
    cta_config: Optional[dict] = None,
    webhook_url: Optional[str] = None,
) -> str:
    """创建批量任务，返回 batch_id。"""
    batch_id = utils.get_uuid()
    os.makedirs(_batch_dir(batch_id), exist_ok=True)

    batch = BatchTask(
        batch_id=batch_id,
        product_name=product_name,
        product_description=product_description,
        livestream_purpose=livestream_purpose,
        raw_script=raw_script,
        material_paths=material_paths or [],
        video_aspect=video_aspect,
        video_clip_duration=video_clip_duration,
        subtitle_enabled=subtitle_enabled,
        font_name=font_name,
        text_fore_color=text_fore_color,
        font_size=font_size,
        bgm_type=bgm_type,
        bgm_file=bgm_file,
        cta_enabled=cta_enabled,
        max_concurrent=max_concurrent,
        motion_intensity=motion_intensity,
        cta_config=cta_config,
        webhook_url=webhook_url or "",
    )

    _batch_tasks[batch_id] = batch
    logger.info(f"Created batch task: {batch_id}")
    return batch_id


def execute_batch(
    batch_id: str,
    variants: Optional[List[dict]] = None,
    voice_names: Optional[List[str]] = None,
):
    """
    执行批量生成的完整流水线。

    如果提供了 variants，则直接使用（跳过 Stage 1-3）。
    否则执行完整的三阶段流程。
    """
    batch = _batch_tasks.get(batch_id)
    if not batch:
        logger.error(f"Batch {batch_id} not found")
        return

    try:
        # ── Phase A: 素材分析（如有上传素材） ──
        if batch.material_paths:
            batch.state = BatchState.analyzing.value
            batch.progress = 5
            logger.info(f"[Batch {batch_id}] Phase A: Analyzing {len(batch.material_paths)} materials")

            analyzed = analyze_multiple_materials(
                file_paths=batch.material_paths,
                product_context=batch.product_name,
                task_id=batch_id,
            )
            batch.analyzed_segments = [seg.to_dict() for seg in analyzed]
            batch.progress = 15
            logger.info(f"  Analyzed {len(analyzed)} segments")

        # ── Phase B: 口播稿处理 ──
        if not variants:
            batch.state = BatchState.scripting.value
            batch.progress = 20

            # Stage 1: 优化口播稿
            logger.info(f"[Batch {batch_id}] Phase B.1: Optimizing script")
            if batch.raw_script:
                batch.optimized_script = optimize_script(
                    raw_script=batch.raw_script,
                    product_name=batch.product_name,
                    product_description=batch.product_description,
                    livestream_purpose=batch.livestream_purpose,
                )
            batch.progress = 25

            # Stage 2: 生成变体
            promo_cfg = config._cfg.get("promo", {})
            default_count = promo_cfg.get("default_variant_count", 5)
            default_styles = promo_cfg.get("default_styles", None)

            logger.info(f"[Batch {batch_id}] Phase B.2: Generating {default_count} variants")
            script_variants = generate_variants(
                optimized_script=batch.optimized_script,
                product_name=batch.product_name,
                styles=default_styles,
                count=default_count,
            )

            # Stage 3: 素材编排
            logger.info(f"[Batch {batch_id}] Phase B.3: Planning materials")
            for sv in script_variants:
                plan_materials(
                    variant=sv,
                    analyzed_segments=batch.analyzed_segments or None,
                    product_name=batch.product_name,
                )

            variants = [sv.to_dict() for sv in script_variants]
            batch.progress = 35

        # ── Phase C: 分配音色 ──
        count = len(variants)
        if not voice_names or len(voice_names) < count:
            voice_names = _assign_voices(count, voice_names)

        # ── Phase D: 创建视频任务列表 ──
        batch.state = BatchState.generating.value
        batch.video_tasks = []

        for i, variant in enumerate(variants):
            vt = VideoTask(
                video_id=f"v-{i+1:03d}",
                variant=variant,
                voice_name=voice_names[i] if i < len(voice_names) else voice_names[0],
                state=VideoState.queued.value,
            )
            batch.video_tasks.append(vt)

        logger.info(f"[Batch {batch_id}] Phase D: {count} video tasks created, starting generation")

        # ── Phase E: 并行生成视频 ──
        max_workers = min(batch.max_concurrent, count)
        completed_count = 0
        failed_count = 0

        # 使用线程池而非进程池（共享内存状态更方便）
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for vt in batch.video_tasks:
                future = executor.submit(
                    generate_single_video,
                    batch_id=batch_id,
                    video_task=vt,
                    video_aspect=batch.video_aspect,
                    video_clip_duration=batch.video_clip_duration,
                    subtitle_enabled=batch.subtitle_enabled,
                    font_name=batch.font_name,
                    text_fore_color=batch.text_fore_color,
                    font_size=batch.font_size,
                    bgm_type=batch.bgm_type,
                    bgm_file=batch.bgm_file,
                    analyzed_segments=batch.analyzed_segments,
                    cta_enabled=batch.cta_enabled,
                )
                futures[future] = vt.video_id

            for future in as_completed(futures):
                video_id = futures[future]
                try:
                    result = future.result()
                    if result.get("success"):
                        completed_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"  [{video_id}] Unexpected error: {e}")
                    failed_count += 1

                # 更新整体进度
                done = completed_count + failed_count
                batch.progress = 35 + (done / count) * 65

        # ── Phase F: 汇总结果 ──
        if failed_count == 0:
            batch.state = BatchState.completed.value
        elif completed_count == 0:
            batch.state = BatchState.failed.value
        else:
            batch.state = BatchState.partial_failed.value

        batch.progress = 100

        # 创建 zip 包
        if completed_count > 0:
            _create_zip_archive(batch_id)

        logger.success(
            f"[Batch {batch_id}] Complete: "
            f"{completed_count} succeeded, {failed_count} failed"
        )

        # 触发 Webhook 回调
        if batch.webhook_url:
            _send_webhook_callback(batch)

    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"[Batch {batch_id}] Batch execution failed: {error_msg}")
        batch.state = BatchState.failed.value
        batch.progress = 100
        if batch.webhook_url:
            _send_webhook_callback(batch)


# ────────────────────────── 便捷查询 ──────────────────────────

def get_batch_videos(batch_id: str) -> List[dict]:
    """获取批量任务中所有视频的状态。"""
    batch = _batch_tasks.get(batch_id)
    if not batch:
        return []
    return [vt.to_dict() for vt in batch.video_tasks]


def get_batch_zip_path(batch_id: str) -> str:
    """获取批量任务的 zip 包路径。"""
    zip_path = os.path.join(_batch_dir(batch_id), f"batch-{batch_id}.zip")
    if os.path.exists(zip_path):
        return zip_path
    return ""


def get_video_output_path(batch_id: str, video_id: str) -> str:
    """获取指定视频的输出 file 路径。"""
    batch = _batch_tasks.get(batch_id)
    if not batch:
        return ""
    for vt in batch.video_tasks:
        if vt.video_id == video_id:
            return vt.output_path
    return ""


# ────────────────────────── Phase 11: 极速热合并 & Segment 局部微调 ──────────────────────────

def remux_video(
    batch_id: str,
    video_id: str,
    new_subtitle_content: Optional[str] = None,
    new_bgm_file: Optional[str] = None,
    bgm_volume: Optional[float] = None,
) -> dict:
    """
    极速字幕/背景音乐热合并 (Remux)。
    """
    logger.info(f"[Batch {batch_id}] Remuxing video {video_id}")
    batch = get_batch(batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    video_task = None
    for vt in batch.video_tasks:
        if vt.video_id == video_id:
            video_task = vt
            break
    
    if not video_task:
        raise ValueError(f"Video {video_id} not found in batch {batch_id}")

    work_dir = _video_dir(batch_id, video_id)
    combined_video_path = os.path.join(work_dir, "combined.mp4")
    if not os.path.exists(combined_video_path):
        raise FileNotFoundError(f"Base video not found: {combined_video_path}")

    # 更新字幕
    subtitle_path = os.path.join(work_dir, "subtitle.srt")
    if new_subtitle_content is not None:
        with open(subtitle_path, "w", encoding="utf-8") as f:
            f.write(new_subtitle_content)
        logger.info(f"Updated subtitle.srt for {video_id}")

    # BGM 配置
    current_bgm_file = new_bgm_file if new_bgm_file is not None else batch.bgm_file
    current_bgm_volume = bgm_volume if bgm_volume is not None else 0.2

    audio_file = os.path.join(work_dir, "audio.mp3")
    if not os.path.exists(audio_file):
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    params = VideoParams(
        video_subject=video_task.variant.get("style", "推广视频"),
        video_aspect=VideoAspect(batch.video_aspect),
        video_concat_mode=VideoConcatMode.random,
        video_transition_mode=VideoTransitionMode.shuffle,
        video_clip_duration=batch.video_clip_duration,
        video_count=1,
        subtitle_enabled=batch.subtitle_enabled,
        font_name=batch.font_name,
        text_fore_color=batch.text_fore_color,
        font_size=batch.font_size,
        bgm_type=batch.bgm_type,
        bgm_file=current_bgm_file,
        bgm_volume=current_bgm_volume,
        voice_name=video_task.voice_name,
        voice_rate=1.0,
    )

    final_video_path = os.path.join(work_dir, f"final-{video_id}.mp4")
    if os.path.exists(final_video_path):
        try:
            os.remove(final_video_path)
        except Exception:
            pass

    # 重新生成视频
    video.generate_video(
        video_path=combined_video_path,
        audio_path=audio_file,
        subtitle_path=subtitle_path if os.path.exists(subtitle_path) else "",
        output_file=final_video_path,
        params=params,
    )

    # 重新应用 Remotion 叠层
    if batch.cta_enabled:
        from app.services import remotion_render
        if remotion_render.is_remotion_available():
            logger.info(f"  [{video_id}] Remotion is enabled, re-applying CTA overlay...")
            cta_config = batch.cta_config or {}
            
            audio_duration = 30.0
            try:
                from moviepy.audio.io.AudioFileClip import AudioFileClip
                audio_clip = AudioFileClip(audio_file)
                audio_duration = audio_clip.duration
                audio_clip.close()
            except Exception:
                pass

            # 底部 CTA 引导层
            cta_webm = os.path.join(work_dir, "cta_overlay.webm")
            cta_duration_sec = 3.0
            start_time = max(0.0, audio_duration - cta_duration_sec)
            cta_text = video_task.variant.get("cta_text", "点击下方链接，立即抢购！")
            if cta_config and cta_config.get("cta_text"):
                cta_text = cta_config.get("cta_text")

            sub_text = "限时秒杀 • 抢完即止"
            if cta_config and cta_config.get("price"):
                sub_text = f"限时秒杀价 ¥{cta_config.get('price')} • 抢完即止"

            rendered_cta = remotion_render.render_cta_overlay(
                output_path=cta_webm,
                text=cta_text,
                sub_text=sub_text,
                width=1080 if batch.video_aspect == "9:16" else 1920,
                height=1920 if batch.video_aspect == "9:16" else 1080,
            )
            if rendered_cta and os.path.exists(rendered_cta):
                overlayed_video_path = os.path.join(work_dir, f"overlayed-cta-{video_id}.mp4")
                success_overlay = remotion_render.composite_overlay(
                    base_video=final_video_path,
                    overlay_video=rendered_cta,
                    output_path=overlayed_video_path,
                    start_time=start_time,
                )
                if success_overlay and os.path.exists(success_overlay):
                    final_video_path = overlayed_video_path

            # 价格牌 CTA 标签
            if cta_config and cta_config.get("price"):
                price_webm = os.path.join(work_dir, "price_tag.webm")
                current_price = cta_config.get("price")
                original_price = cta_config.get("original_price", "")
                
                discount = ""
                if original_price:
                    try:
                        diff = float(original_price) - float(current_price)
                        if diff > 0:
                            discount = f"立减{int(diff)}元"
                    except Exception:
                        pass

                rendered_price = remotion_render.render_price_tag(
                    output_path=price_webm,
                    current_price=current_price,
                    original_price=original_price,
                    discount=discount,
                    width=1080 if batch.video_aspect == "9:16" else 1920,
                    height=1920 if batch.video_aspect == "9:16" else 1080,
                )
                if rendered_price and os.path.exists(rendered_price):
                    overlayed_video_path = os.path.join(work_dir, f"overlayed-price-{video_id}.mp4")
                    success_overlay = remotion_render.composite_overlay(
                        base_video=final_video_path,
                        overlay_video=rendered_price,
                        output_path=overlayed_video_path,
                        start_time=0.5,
                    )
                    if success_overlay and os.path.exists(success_overlay):
                        final_video_path = overlayed_video_path

    thumbnail_path = os.path.join(work_dir, "thumbnail.jpg")
    _generate_thumbnail(final_video_path, thumbnail_path)

    video_task.state = VideoState.completed.value
    video_task.progress = 100.0
    video_task.output_path = final_video_path
    video_task.thumbnail_path = thumbnail_path
    _update_batch_video(batch_id, video_task)

    _create_zip_archive(batch_id)

    return {
        "success": True,
        "video_id": video_id,
        "output_path": final_video_path,
        "thumbnail_path": thumbnail_path,
    }


def update_video_segment(
    batch_id: str,
    video_id: str,
    segment_index: int,
    new_segment_data: dict,
) -> dict:
    """
    段落级 Timeline 局部微调与极速热合并。
    """
    logger.info(f"[Batch {batch_id}] Updating segment {segment_index} for video {video_id}")
    batch = get_batch(batch_id)
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    video_task = None
    for vt in batch.video_tasks:
        if vt.video_id == video_id:
            video_task = vt
            break
    
    if not video_task:
        raise ValueError(f"Video {video_id} not found in batch {batch_id}")

    segments = video_task.variant.get("segments", [])
    if segment_index < 0 or segment_index >= len(segments):
        raise ValueError(f"Invalid segment index: {segment_index}")

    seg = segments[segment_index]
    for k, v in new_segment_data.items():
        seg[k] = v

    work_dir = _video_dir(batch_id, video_id)
    seg_dir = os.path.join(work_dir, f"seg-{segment_index}")
    if os.path.exists(seg_dir):
        shutil.rmtree(seg_dir)
    os.makedirs(seg_dir, exist_ok=True)

    strategy = seg.get("material_strategy", "ai_image")
    ai_prompt = seg.get("ai_prompt", "")
    stock_keywords = seg.get("stock_keywords", [])
    user_path = seg.get("matched_user_segment_path", "")
    max_clip_duration = batch.video_clip_duration

    new_segment_video_path = ""
    
    try:
        if strategy == "user_upload" and user_path and os.path.exists(user_path):
            new_segment_video_path = user_path
        elif strategy in ["ai_image", "ai_video"]:
            if ai_prompt:
                seg_task_id = f"{batch_id}/{video_id}/seg-{segment_index}"
                image_paths = material.generate_images_flux(
                    task_id=seg_task_id,
                    search_terms=[ai_prompt],
                    audio_duration=max_clip_duration,
                    max_clip_duration=max_clip_duration,
                    video_aspect=VideoAspect(batch.video_aspect),
                )
                if image_paths:
                    image_materials = []
                    for ip in image_paths:
                        item = MaterialInfo()
                        item.provider = "flux-1-schnell"
                        item.url = ip
                        item.duration = max_clip_duration
                        image_materials.append(item)
                    
                    motion_intensity = batch.motion_intensity
                    processed = video.preprocess_video(
                        materials=image_materials,
                        clip_duration=max_clip_duration,
                        motion_intensity=motion_intensity,
                    )
                    for m in processed:
                        if m.url.endswith(".mp4"):
                            new_segment_video_path = m.url
                            break
        elif strategy == "stock":
            keywords = stock_keywords or ["product", "beauty"]
            for kw in keywords[:2]:
                items = material.search_videos_pexels(
                    search_term=kw,
                    minimum_duration=max_clip_duration,
                    video_aspect=VideoAspect(batch.video_aspect),
                )
                for item in items[:2]:
                    saved = material.save_video(video_url=item.url)
                    if saved:
                        new_segment_video_path = saved
                        break
                if new_segment_video_path:
                    break
    except Exception as e:
        logger.error(f"Failed to regenerate material for segment {segment_index}: {e}")
        raise e

    if not new_segment_video_path:
        logger.warning(f"Could not fetch new material for segment {segment_index}, reusing existing segment material.")
        if hasattr(video_task, 'segment_video_paths') and video_task.segment_video_paths and len(video_task.segment_video_paths) > segment_index:
            new_segment_video_path = video_task.segment_video_paths[segment_index]

    if not new_segment_video_path:
        raise RuntimeError(f"Failed to obtain material for segment {segment_index}")

    if not hasattr(video_task, 'segment_video_paths') or not video_task.segment_video_paths:
        video_task.segment_video_paths = []
        for idx in range(len(segments)):
            if idx == segment_index:
                video_task.segment_video_paths.append(new_segment_video_path)
            else:
                found_path = ""
                exist_seg_dir = os.path.join(work_dir, f"seg-{idx}")
                if os.path.exists(exist_seg_dir):
                    for root, dirs, files in os.walk(exist_seg_dir):
                        for file in files:
                            if file.endswith(".mp4"):
                                found_path = os.path.join(root, file)
                                break
                        if found_path:
                            break
                if not found_path:
                    found_path = new_segment_video_path
                video_task.segment_video_paths.append(found_path)
    else:
        while len(video_task.segment_video_paths) < len(segments):
            video_task.segment_video_paths.append(new_segment_video_path)
        video_task.segment_video_paths[segment_index] = new_segment_video_path

    audio_file = os.path.join(work_dir, "audio.mp3")
    combined_video_path = os.path.join(work_dir, "combined.mp4")
    if os.path.exists(combined_video_path):
        try:
            os.remove(combined_video_path)
        except Exception:
            pass

    logger.info("Combining segment videos to new combined.mp4")
    video.combine_videos(
        combined_video_path=combined_video_path,
        video_paths=video_task.segment_video_paths,
        audio_file=audio_file,
        video_aspect=VideoAspect(batch.video_aspect),
        video_concat_mode=VideoConcatMode.random,
        video_transition_mode=VideoTransitionMode.shuffle,
        max_clip_duration=batch.video_clip_duration,
        threads=2,
    )

    return remux_video(
        batch_id=batch_id,
        video_id=video_id,
        new_subtitle_content=None,
        new_bgm_file=batch.bgm_file,
        bgm_volume=0.2,
    )


# ────────────────────────── Phase 12: 自动清理与 Webhook ──────────────────────────

import requests
import threading
import time

def _send_webhook_callback(batch: BatchTask):
    """向指定的 webhook_url 发送批处理完成通知"""
    if not batch.webhook_url:
        return

    logger.info(f"[Batch {batch.batch_id}] Triggering webhook callback to {batch.webhook_url}")
    
    videos_data = []
    base_url = config.app.get("server_url", "http://127.0.0.1:8080")
    
    for vt in batch.video_tasks:
        if vt.state == VideoState.completed.value:
            videos_data.append({
                "video_id": vt.video_id,
                "style": vt.variant.get("style", ""),
                "full_script": vt.variant.get("full_script", ""),
                "download_url": f"{base_url}/v1/promo/batch/{batch.batch_id}/videos/{vt.video_id}/download",
                "preview_url": f"{base_url}/v1/promo/batch/{batch.batch_id}/videos/{vt.video_id}/preview",
                "thumbnail_url": f"{base_url}/tasks/{batch.batch_id}/{vt.video_id}/thumbnail.jpg" if vt.thumbnail_path else "",
            })

    payload = {
        "event": "batch_completed",
        "batch_id": batch.batch_id,
        "product_name": batch.product_name,
        "state": batch.state,
        "zip_download_url": f"{base_url}/v1/promo/batch/{batch.batch_id}/download" if batch.state in (BatchState.completed.value, BatchState.partial_failed.value) else "",
        "videos": videos_data,
        "timestamp": time.time(),
    }

    try:
        def post_request():
            try:
                res = requests.post(batch.webhook_url, json=payload, timeout=10)
                logger.info(f"Webhook callback response: {res.status_code}")
            except Exception as ex:
                logger.warning(f"Failed to post to webhook: {ex}")

        threading.Thread(target=post_request, daemon=True).start()
    except Exception as e:
        logger.warning(f"Failed to trigger webhook thread: {e}")


def start_cleanup_daemon():
    """启动自动清理守护线程，每 12 小时扫描清理 7 天前的旧任务缓存与临时帧"""
    def run_cleanup():
        while True:
            try:
                logger.info("Running storage cleanup daemon...")
                tasks_root = utils.task_dir()
                if os.path.exists(tasks_root):
                    now = time.time()
                    seven_days_sec = 7 * 24 * 3600
                    for name in os.listdir(tasks_root):
                        path = os.path.join(tasks_root, name)
                        if os.path.isdir(path):
                            mtime = os.path.getmtime(path)
                            if now - mtime > seven_days_sec:
                                logger.info(f"Removing old task directory: {path}")
                                shutil.rmtree(path)
                
                cache_root = utils.storage_dir("cache_videos")
                if os.path.exists(cache_root):
                    now = time.time()
                    for name in os.listdir(cache_root):
                        path = os.path.join(cache_root, name)
                        if os.path.isfile(path):
                            mtime = os.path.getmtime(path)
                            if now - mtime > 7 * 24 * 3600:
                                logger.info(f"Removing old cache video: {path}")
                                os.remove(path)
            except Exception as e:
                logger.error(f"Error in storage cleanup: {e}")
            
            time.sleep(12 * 3600)

    t = threading.Thread(target=run_cleanup, daemon=True, name="StorageCleanupDaemon")
    t.start()
    logger.info("Storage cleanup daemon started")

# 启动自动清理守护进程
start_cleanup_daemon()

