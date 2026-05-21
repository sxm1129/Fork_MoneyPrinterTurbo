"""
推广视频批量生成 API 端点。

拆分为多个独立端点，前端可以逐步调用，每步有审核机会：
  1. 上传素材
  2. 分析素材
  3. 优化口播稿
  4. 生成风格变体
  5. 提交批量生成任务
  6. 查询状态
  7. 下载结果
"""

import os
import glob
from typing import List, Optional

from fastapi import BackgroundTasks, Path, Query, Request, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import (
    PromoAnalyzeRequest,
    PromoOptimizeScriptRequest,
    PromoGenerateVariantsRequest,
    PromoDiagnoseRequest,
    PromoBatchRequest,
    PromoSegmentUpdateRequest,
    PromoRemuxRequest,
    PromoResponse,
    BaseResponse,
)
from app.services import batch_engine
from app.services.analyzer import analyze_multiple_materials
from app.services.script_engine import (
    optimize_script,
    generate_variants,
    plan_materials,
    diagnose_script,
    SCRIPT_STYLES,
)
from app.utils import utils

router = new_router()

# 存储已上传素材的映射：material_id -> file_path
_uploaded_materials = {}


# ────────────────────────── 1. 上传素材 ──────────────────────────

@router.post(
    "/promo/upload",
    response_model=BaseResponse,
    summary="Upload material for promo video batch generation",
)
async def upload_promo_material(request: Request, file: UploadFile = File(...)):
    """上传素材文件（视频/图片），返回 material_id。"""
    request_id = base.get_task_id(request)
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()

    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png", "webp")
    if not filename.lower().endswith(allowed_suffixes):
        raise HttpException(
            task_id="",
            status_code=400,
            message=f"Unsupported file format. Allowed: {', '.join(allowed_suffixes)}",
        )

    material_id = utils.get_uuid()
    save_dir = utils.storage_dir("promo_materials", create=True)
    # 保留原始扩展名
    ext = os.path.splitext(filename)[1]
    save_path = os.path.join(save_dir, f"{material_id}{ext}")

    with open(save_path, "wb+") as buffer:
        file.file.seek(0)
        buffer.write(file.file.read())

    _uploaded_materials[material_id] = save_path
    logger.info(f"Promo material uploaded: {material_id} -> {save_path}")

    return utils.get_response(200, {
        "material_id": material_id,
        "filename": filename,
        "file_path": save_path,
    })


# ────────────────────────── 2. 分析素材 ──────────────────────────

@router.post(
    "/promo/analyze",
    response_model=BaseResponse,
    summary="Analyze uploaded materials with AI",
)
async def analyze_promo_materials(request: Request, body: PromoAnalyzeRequest):
    """触发素材分析，返回分析结果（含标签和评分）。"""
    # 解析素材路径
    file_paths = []
    for mid in body.material_ids:
        fp = _uploaded_materials.get(mid)
        if fp and os.path.exists(fp):
            file_paths.append(fp)
        else:
            logger.warning(f"Material not found: {mid}")

    if not file_paths:
        raise HttpException(
            task_id="",
            status_code=400,
            message="No valid materials to analyze",
        )

    segments = analyze_multiple_materials(
        file_paths=file_paths,
        product_context=body.product_name,
    )

    return utils.get_response(200, {
        "segments": [seg.to_dict() for seg in segments],
        "total": len(segments),
    })


# ────────────────────────── 3. 优化口播稿 ──────────────────────────

@router.post(
    "/promo/optimize-script",
    response_model=BaseResponse,
    summary="Optimize raw script for promo videos",
)
async def optimize_promo_script(request: Request, body: PromoOptimizeScriptRequest):
    """提交原始口播稿+产品信息，返回优化后的标准稿。"""
    optimized = optimize_script(
        raw_script=body.raw_script,
        product_name=body.product_name,
        product_description=body.product_description,
        livestream_purpose=body.livestream_purpose,
        target_language=body.target_language,
    )

    if not optimized:
        raise HttpException(
            task_id="",
            status_code=500,
            message="Failed to optimize script",
        )

    return utils.get_response(200, {
        "optimized_script": optimized,
    })


@router.post(
    "/promo/diagnose",
    response_model=BaseResponse,
    summary="Diagnose script viral potential",
)
async def diagnose_promo_script(request: Request, body: PromoDiagnoseRequest):
    """口播稿爆款雷达打分诊断。"""
    result = diagnose_script(
        script=body.script,
        product_name=body.product_name,
    )
    return utils.get_response(200, result)


# ────────────────────────── 4. 生成风格变体 ──────────────────────────

@router.post(
    "/promo/generate-variants",
    response_model=BaseResponse,
    summary="Generate N style variants from optimized script",
)
async def generate_promo_variants(
    request: Request, body: PromoGenerateVariantsRequest
):
    """基于标准稿生成 N 条风格变体。"""
    variants = generate_variants(
        optimized_script=body.optimized_script,
        product_name=body.product_name,
        styles=body.styles,
        count=body.count,
        target_language=body.target_language,
    )

    return utils.get_response(200, {
        "variants": [v.to_dict() for v in variants],
        "total": len(variants),
        "available_styles": list(SCRIPT_STYLES.keys()),
    })


# ────────────────────────── 5. 提交批量任务 ──────────────────────────

@router.post(
    "/promo/batch",
    response_model=PromoResponse,
    summary="Submit batch promo video generation task",
)
async def create_promo_batch(
    background_tasks: BackgroundTasks,
    request: Request,
    body: PromoBatchRequest,
):
    """提交批量推广视频生成任务（异步执行）。"""
    # 解析素材路径
    material_paths = []
    if body.material_ids:
        for mid in body.material_ids:
            fp = _uploaded_materials.get(mid)
            if fp and os.path.exists(fp):
                material_paths.append(fp)

    # 创建批量任务
    batch_id = batch_engine.create_batch(
        product_name=body.product_name,
        raw_script=body.raw_script,
        product_description=body.product_description,
        livestream_purpose=body.livestream_purpose,
        material_paths=material_paths,
        video_aspect=body.video_aspect.value if hasattr(body.video_aspect, 'value') else str(body.video_aspect),
        video_clip_duration=body.video_clip_duration,
        subtitle_enabled=body.subtitle_enabled,
        font_name=body.font_name,
        text_fore_color=body.text_fore_color,
        font_size=body.font_size,
        bgm_type=body.bgm_type,
        bgm_file=body.bgm_file,
        cta_enabled=body.cta_enabled,
        max_concurrent=body.max_concurrent,
        motion_intensity=body.motion_intensity,
        cta_config=body.cta_config,
        webhook_url=body.webhook_url,
    )

    # 异步执行批量生成
    background_tasks.add_task(
        batch_engine.execute_batch,
        batch_id=batch_id,
        variants=body.variants,
        voice_names=body.voice_names,
    )

    logger.success(f"Batch task created: {batch_id}")
    return utils.get_response(200, {"batch_id": batch_id})


# ────────────────────────── 6. 查询状态 ──────────────────────────

@router.get(
    "/promo/batch/{batch_id}",
    response_model=BaseResponse,
    summary="Query batch task status",
)
async def get_promo_batch_status(
    request: Request,
    batch_id: str = Path(..., description="Batch task ID"),
):
    """查询批量任务状态（含每条视频的精细状态）。"""
    status = batch_engine.get_batch_status(batch_id)
    if not status:
        raise HttpException(
            task_id=batch_id,
            status_code=404,
            message="Batch task not found",
        )

    return utils.get_response(200, status)


@router.get(
    "/promo/batches",
    response_model=BaseResponse,
    summary="List all batch tasks",
)
async def list_promo_batches(request: Request):
    """列出所有批量任务。"""
    batches = batch_engine.list_batches()
    return utils.get_response(200, {"batches": batches, "total": len(batches)})


# ────────────────────────── 7. 下载结果 ──────────────────────────

@router.get(
    "/promo/batch/{batch_id}/download",
    summary="Download all videos as zip",
)
async def download_promo_batch(
    request: Request,
    batch_id: str = Path(..., description="Batch task ID"),
):
    """批量下载所有完成的视频（zip 打包）。"""
    zip_path = batch_engine.get_batch_zip_path(batch_id)
    if not zip_path or not os.path.exists(zip_path):
        raise HttpException(
            task_id=batch_id,
            status_code=404,
            message="Zip archive not found. Task may still be in progress.",
        )

    return FileResponse(
        path=zip_path,
        filename=f"promo-batch-{batch_id}.zip",
        media_type="application/zip",
    )


@router.get(
    "/promo/batch/{batch_id}/videos/{video_id}/preview",
    summary="Preview a single promo video",
)
async def preview_promo_video(
    request: Request,
    batch_id: str = Path(...),
    video_id: str = Path(...),
):
    """流式预览单条推广视频。"""
    video_path = batch_engine.get_video_output_path(batch_id, video_id)
    if not video_path or not os.path.exists(video_path):
        raise HttpException(
            task_id=batch_id,
            status_code=404,
            message=f"Video {video_id} not found",
        )

    video_size = os.path.getsize(video_path)
    range_header = request.headers.get("Range")
    start, end = 0, video_size - 1
    length = video_size

    if range_header:
        range_ = range_header.split("bytes=")[1]
        start, end = [int(part) if part else None for part in range_.split("-")]
        if start is None:
            start = video_size - end
            end = video_size - 1
        if end is None:
            end = video_size - 1
        length = end - start + 1

    def file_iterator(file_path, offset=0, bytes_to_read=None):
        with open(file_path, "rb") as f:
            f.seek(offset, os.SEEK_SET)
            remaining = bytes_to_read or video_size
            while remaining > 0:
                chunk = min(4096, remaining)
                data = f.read(chunk)
                if not data:
                    break
                remaining -= len(data)
                yield data

    response = StreamingResponse(
        file_iterator(video_path, start, length), media_type="video/mp4"
    )
    response.headers["Content-Range"] = f"bytes {start}-{end}/{video_size}"
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Length"] = str(length)
    response.status_code = 206

    return response


@router.get(
    "/promo/batch/{batch_id}/videos/{video_id}/download",
    summary="Download a single promo video",
)
async def download_promo_video(
    request: Request,
    batch_id: str = Path(...),
    video_id: str = Path(...),
):
    """下载单条推广视频。"""
    video_path = batch_engine.get_video_output_path(batch_id, video_id)
    if not video_path or not os.path.exists(video_path):
        raise HttpException(
            task_id=batch_id,
            status_code=404,
            message=f"Video {video_id} not found",
        )

    filename = f"promo-{video_id}.mp4"
    return FileResponse(
        path=video_path,
        filename=filename,
        media_type="video/mp4",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ────────────────────────── 8. 可用风格列表 ──────────────────────────

@router.get(
    "/promo/styles",
    response_model=BaseResponse,
    summary="Get available script styles",
)
async def get_promo_styles(request: Request):
    """获取所有可用的口播稿风格。"""
    return utils.get_response(200, {
        "styles": list(SCRIPT_STYLES.keys()),
    })


# ────────────────────────── 9. Timeline 局部微调与 Remux ──────────────────────────

@router.post(
    "/promo/batch/{batch_id}/videos/{video_id}/segment/{index}/update",
    response_model=BaseResponse,
    summary="Update a specific video segment",
)
async def update_promo_video_segment(
    request: Request,
    body: PromoSegmentUpdateRequest,
    batch_id: str = Path(...),
    video_id: str = Path(...),
    index: int = Path(...),
):
    """Timeline 段落局部微调，仅重新生成被修改的分镜片段并热拼接。"""
    try:
        res = batch_engine.update_video_segment(
            batch_id=batch_id,
            video_id=video_id,
            segment_index=index,
            new_segment_data=body.new_segment_data,
        )
        return utils.get_response(200, res)
    except Exception as e:
        logger.error(f"Failed to update segment: {e}")
        raise HttpException(
            task_id=batch_id,
            status_code=500,
            message=str(e),
        )


@router.post(
    "/promo/batch/{batch_id}/videos/{video_id}/remux",
    response_model=BaseResponse,
    summary="Fast remux video subtitles and background music",
)
async def remux_promo_video(
    request: Request,
    body: PromoRemuxRequest,
    batch_id: str = Path(...),
    video_id: str = Path(...),
):
    """极速 3 秒热合并字幕或背景音乐。"""
    try:
        res = batch_engine.remux_video(
            batch_id=batch_id,
            video_id=video_id,
            new_subtitle_content=body.new_subtitle_content,
            new_bgm_file=body.new_bgm_file,
            bgm_volume=body.bgm_volume,
        )
        return utils.get_response(200, res)
    except Exception as e:
        logger.error(f"Failed to remux video: {e}")
        raise HttpException(
            task_id=batch_id,
            status_code=500,
            message=str(e),
        )


@router.get(
    "/promo/storage-status",
    response_model=BaseResponse,
    summary="Get server disk occupancy",
)
async def get_storage_status(request: Request):
    """返回磁盘空间占用百分比和字节数。"""
    import shutil
    try:
        total, used, free = shutil.disk_usage("/")
        used_percent = round((used / total) * 100, 2)
        return utils.get_response(200, {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_percent": used_percent,
        })
    except Exception as e:
        logger.error(f"Failed to get storage status: {e}")
        raise HttpException(
            task_id="",
            status_code=500,
            message=str(e),
        )

