import os
import random
import threading
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()


def _get_tls_verify() -> bool:
    # 默认开启 TLS 证书校验，防止素材搜索和下载过程被中间人篡改。
    # 仅在企业代理、自签证书等明确需要的场景下，允许用户通过
    # `config.toml` 显式设置 `tls_verify = false` 临时关闭。
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        clip = None
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    f"failed to remove invalid video file: {video_path}, error: {str(remove_error)}"
                )
        finally:
            if clip is not None:
                try:
                    clip.close()
                except Exception as close_error:
                    logger.warning(
                        f"failed to close video clip: {video_path}, error: {str(close_error)}"
                    )
    return ""


def generate_images_flux(
    task_id: str,
    search_terms: List[str],
    audio_duration: float,
    max_clip_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[str]:
    import base64
    import math
    from openai import OpenAI

    api_key = config.app.get("openai_api_key")
    base_url = config.app.get("openai_base_url")
    if not api_key:
        raise ValueError("openai_api_key is not set in config.toml")

    client = OpenAI(api_key=api_key, base_url=base_url)

    num_clips = math.ceil(audio_duration / max_clip_duration)
    if num_clips <= 0:
        num_clips = 1

    # Map selected VideoAspect ratio to optimal standard image generation dimensions:
    # 9:16 (portrait) -> 1024x1792
    # 16:9 (landscape) -> 1792x1024
    # 1:1 (square) -> 1024x1024
    img_size = "1024x1024"
    if video_aspect:
        aspect_str = video_aspect.value if hasattr(video_aspect, "value") else str(video_aspect)
        if aspect_str == "9:16":
            img_size = "1024x1792"
        elif aspect_str == "16:9":
            img_size = "1792x1024"
        elif aspect_str == "1:1":
            img_size = "1024x1024"

    logger.info(
        f"generating {num_clips} images ({img_size}) using flux-1-schnell for search terms: {search_terms}"
    )

    task_dir = utils.task_dir(task_id)
    if not os.path.exists(task_dir):
        os.makedirs(task_dir)

    image_paths = []
    for i in range(num_clips):
        term = search_terms[i % len(search_terms)] if search_terms else "a beautiful scene"
        prompt = f"A beautiful, high-quality, photorealistic depiction of: {term}. Cinematic lighting, highly detailed, 8k resolution."
        logger.info(f"generating image {i+1}/{num_clips} with prompt: {prompt}")

        try:
            response = client.images.generate(
                model="flux-1-schnell",
                prompt=prompt,
                n=1,
                size=img_size
            )
            data = response.data[0]

            # Save the image file
            save_path = os.path.join(task_dir, f"flux-{i+1}.png")

            if hasattr(data, "b64_json") and data.b64_json:
                img_data = base64.b64decode(data.b64_json)
                with open(save_path, "wb") as f:
                    f.write(img_data)
                logger.info(f"saved image from b64_json: {save_path}")
                image_paths.append(save_path)
            elif hasattr(data, "url") and data.url:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                }
                res = requests.get(
                    data.url,
                    headers=headers,
                    proxies=config.proxy,
                    verify=_get_tls_verify(),
                    timeout=60
                )
                with open(save_path, "wb") as f:
                    f.write(res.content)
                logger.info(f"saved image from url: {save_path}")
                image_paths.append(save_path)
            else:
                logger.error(f"no url or b64_json returned in image generation for prompt: {prompt}")
        except Exception as e:
            logger.error(f"failed to generate image {i+1} using flux-1-schnell: {str(e)}")

    return image_paths


AI_VIDEO_MODELS = {
    "happyhorse-1.0-t2v",
    "happyhorse-1.0-i2v",
    "wan2.7-i2v",
    "volcengine/doubao-seedance-1.5-pro",
}


def generate_images_flux_for_video(
    task_id: str,
    search_terms: List[str],
    num_clips: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[dict]:
    import base64
    from openai import OpenAI

    api_key = config.app.get("openai_api_key")
    base_url = config.app.get("openai_base_url")
    if not api_key:
        raise ValueError("openai_api_key is not set in config.toml")

    client = OpenAI(api_key=api_key, base_url=base_url)

    img_size = "1024x1024"
    if video_aspect:
        aspect_str = video_aspect.value if hasattr(video_aspect, "value") else str(video_aspect)
        if aspect_str == "9:16":
            img_size = "1024x1792"
        elif aspect_str == "16:9":
            img_size = "1792x1024"
        elif aspect_str == "1:1":
            img_size = "1024x1024"

    logger.info(
        f"generating {num_clips} flux starting images ({img_size}) for video model"
    )

    task_dir = utils.task_dir(task_id)
    if not os.path.exists(task_dir):
        os.makedirs(task_dir)

    results = []
    for i in range(num_clips):
        term = search_terms[i % len(search_terms)] if search_terms else "a beautiful scene"
        prompt = f"A beautiful, high-quality, photorealistic depiction of: {term}. Cinematic lighting, highly detailed, 8k resolution."
        logger.info(f"generating image {i+1}/{num_clips} with prompt: {prompt}")

        try:
            response = client.images.generate(
                model="flux-1-schnell",
                prompt=prompt,
                n=1,
                size=img_size
            )
            data = response.data[0]
            save_path = os.path.join(task_dir, f"flux-start-{i+1}.png")
            remote_url = None

            if hasattr(data, "url") and data.url:
                remote_url = data.url
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                }
                res = requests.get(
                    data.url,
                    headers=headers,
                    proxies=config.proxy,
                    verify=_get_tls_verify(),
                    timeout=60
                )
                with open(save_path, "wb") as f:
                    f.write(res.content)
                logger.info(f"saved starting image from url: {save_path}")
            elif hasattr(data, "b64_json") and data.b64_json:
                img_data = base64.b64decode(data.b64_json)
                with open(save_path, "wb") as f:
                    f.write(img_data)
                logger.info(f"saved starting image from b64_json: {save_path}")
            
            results.append({
                "local_path": save_path,
                "remote_url": remote_url,
                "prompt": term
            })
        except Exception as e:
            logger.error(f"failed to generate starting image {i+1} using flux-1-schnell: {str(e)}")

    return results


def generate_videos_ai(
    task_id: str,
    search_terms: List[str],
    model: str,
    audio_duration: float,
    max_clip_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[str]:
    import math
    import time
    
    api_key = config.app.get("openai_api_key")
    base_url = config.app.get("openai_base_url", "https://api-gateway.fusionxlink.com/v1").strip()
    if not api_key:
        raise ValueError("openai_api_key is not set in config.toml")

    # Normalize base_url
    if base_url.endswith("/v1"):
        gateway_url = base_url
    else:
        gateway_url = f"{base_url}/v1" if not base_url.endswith("/") else f"{base_url}v1"

    submit_url = f"{gateway_url}/video/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    num_clips = math.ceil(audio_duration / max_clip_duration)
    if num_clips <= 0:
        num_clips = 1

    logger.info(f"Preparing to generate {num_clips} AI video clips using model: {model}")

    # Stage 1: Generate starting images for Image-to-Video models
    is_i2v = model in ("happyhorse-1.0-i2v", "wan2.7-i2v")
    starting_images = []
    if is_i2v:
        logger.info(f"Model {model} is Image-to-Video. Generating starting images first.")
        starting_images = generate_images_flux_for_video(
            task_id=task_id,
            search_terms=search_terms,
            num_clips=num_clips,
            video_aspect=video_aspect
        )

    # Stage 2: Parallel Submission
    jobs = []
    for i in range(num_clips):
        term = search_terms[i % len(search_terms)] if search_terms else "a beautiful scene"
        prompt = f"A beautiful, high-quality, photorealistic depiction of: {term}. Cinematic style, smooth movement, highly detailed."
        
        payload = {
            "model": model,
            "prompt": prompt
        }

        # If Image-to-Video and starting image is successfully generated
        if is_i2v and i < len(starting_images) and starting_images[i]["remote_url"]:
            remote_url = starting_images[i]["remote_url"]
            payload["image_url"] = remote_url
            payload["img_url"] = remote_url
            logger.info(f"Clip {i+1} using Flux image URL: {remote_url}")

        try:
            logger.info(f"Submitting video task {i+1}/{num_clips}...")
            res = requests.post(
                submit_url,
                json=payload,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=60
            )
            if res.status_code == 201 or res.status_code == 200:
                res_json = res.json()
                job_id = res_json.get("job_id")
                if job_id:
                    logger.info(f"Task {i+1} submitted successfully. Job ID: {job_id}")
                    jobs.append({
                        "index": i,
                        "job_id": job_id,
                        "prompt": prompt,
                        "status": "pending",
                        "video_url": None,
                        "downloaded_path": None
                    })
                else:
                    logger.error(f"Task {i+1} submission returned no job_id: {res.text}")
            else:
                logger.error(f"Task {i+1} submission failed with status {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Failed to submit task {i+1}: {str(e)}")

    if not jobs:
        logger.error("No AI video generation tasks were submitted successfully.")
        return []

    # Stage 3: Parallel Polling
    logger.info("Entering parallel polling loop for AI video generation...")
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    finished_jobs = 0
    total_jobs = len(jobs)
    
    # 30 attempts, 10s sleep each => 300s (5 minutes) timeout
    for attempt in range(30):
        time.sleep(10)
        logger.info(f"[{attempt+1}/30] Polling active AI video jobs ({finished_jobs}/{total_jobs} complete)...")
        
        for job in jobs:
            if job["status"] in ("succeeded", "failed"):
                continue
                
            status_url = f"{gateway_url}/video/jobs/{job['job_id']}"
            try:
                res = requests.get(
                    status_url,
                    headers=headers,
                    proxies=config.proxy,
                    verify=_get_tls_verify(),
                    timeout=30
                )
                if res.status_code == 200:
                    res_json = res.json()
                    status = res_json.get("status") or res_json.get("output", {}).get("task_status", "").lower()
                    
                    if status in ("succeeded", "success"):
                        video_url = res_json.get("result_url") or res_json.get("output", {}).get("video_url")
                        if video_url:
                            logger.info(f"🎉 Job {job['job_id']} succeeded! Downloading video...")
                            saved_path = save_video(video_url=video_url, save_dir=material_directory)
                            if saved_path:
                                job["downloaded_path"] = saved_path
                                job["status"] = "succeeded"
                                finished_jobs += 1
                                logger.info(f"Saved video to: {saved_path}")
                            else:
                                job["status"] = "failed"
                                finished_jobs += 1
                                logger.error(f"Failed to save downloaded video for job {job['job_id']}")
                        else:
                            job["status"] = "failed"
                            finished_jobs += 1
                            logger.error(f"Job succeeded but no video url was found in response: {res_json}")
                    elif status in ("failed", "error", "cancelled"):
                        job["status"] = "failed"
                        finished_jobs += 1
                        logger.error(f"Job {job['job_id']} failed with upstream status: {status}")
                    else:
                        logger.info(f"Job {job['job_id']} status: {status}")
                else:
                    logger.warning(f"Error querying job {job['job_id']} status code {res.status_code}: {res.text}")
            except Exception as e:
                logger.error(f"Exception querying job {job['job_id']}: {str(e)}")

        if finished_jobs >= total_jobs:
            logger.info("All AI video generation tasks have finished.")
            break

    video_paths = []
    for job in jobs:
        if job["status"] == "succeeded" and job["downloaded_path"]:
            video_paths.append(job["downloaded_path"])
        else:
            logger.warning(f"Clip {job['index']+1} (Job ID: {job['job_id']}) did not complete successfully.")

    logger.success(f"Generated and downloaded {len(video_paths)}/{total_jobs} AI video clips.")
    return video_paths


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
) -> List[str]:
    if source in AI_VIDEO_MODELS:
        video_paths = generate_videos_ai(
            task_id=task_id,
            search_terms=search_terms,
            model=source,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            video_aspect=video_aspect
        )
        return video_paths

    if source == "flux-1-schnell":
        # Generate raw images matching the selected video aspect ratio/size
        image_paths = generate_images_flux(
            task_id=task_id,
            search_terms=search_terms,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            video_aspect=video_aspect
        )
        if not image_paths:
            logger.error("no images were generated using flux-1-schnell")
            return []

        # Convert generated images to MaterialInfo format
        image_materials = []
        for path in image_paths:
            item = MaterialInfo()
            item.provider = "flux-1-schnell"
            item.url = path
            item.duration = max_clip_duration
            image_materials.append(item)

        # Preprocess images to .mp4 videos using moviepy (adding zoom effect)
        from app.services import video
        logger.info("preprocessing generated flux images into video clips...")
        processed_materials = video.preprocess_video(
            materials=image_materials,
            clip_duration=max_clip_duration
        )

        # Return processed video file paths
        video_paths = [m.url for m in processed_materials if m.url.endswith(".mp4")]
        logger.success(f"successfully preprocessed {len(video_paths)} flux video clips")
        return video_paths

    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay

    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if video_contact_mode.value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    for item in valid_video_items:
        try:
            logger.info(f"downloading video: {item.url}")
            saved_video_path = save_video(
                video_url=item.url, save_dir=material_directory
            )
            if saved_video_path:
                logger.info(f"video saved: {saved_video_path}")
                video_paths.append(saved_video_path)
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                if total_duration > audio_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                    )
                    break
        except Exception as e:
            logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
    logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
