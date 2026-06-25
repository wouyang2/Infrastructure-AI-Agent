from __future__ import annotations

import base64
import csv
import json
import mimetypes
import os
import re
import tempfile
from io import BytesIO
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


@dataclass
class ImageFinding:
    defect_type: str
    description: str
    location_on_asset: str
    confidence: float
    bounding_box: tuple[int, int, int, int] | None = None
    severity_label: str | None = None


class ImageAnalyzer:
    def analyze(self, image_path: str, asset_type: str) -> list[ImageFinding]:
        raise NotImplementedError


KNOWN_DEFECT_TYPES = {
    "crack",
    "spalling",
    "exposed_rebar",
    "corrosion",
    "leak",
}


class HeuristicImageAnalyzer(ImageAnalyzer):
    DEFECT_KEYWORDS = {
        "crack": ["crack", "cracking", "fracture"],
        "spalling": ["spall", "spalling", "delamination"],
        "leak": ["leak", "seepage", "water"],
        "corrosion": ["corrosion", "rust", "oxidation"],
    }

    def analyze(self, image_path: str, asset_type: str) -> list[ImageFinding]:
        file_name = Path(image_path).name.lower()
        findings: list[ImageFinding] = []

        for defect_type, keywords in self.DEFECT_KEYWORDS.items():
            if any(keyword in file_name for keyword in keywords):
                findings.append(
                    ImageFinding(
                        defect_type=defect_type,
                        description=(
                            f"Image heuristic flagged possible {defect_type} "
                            f"on {asset_type} from file name '{Path(image_path).name}'."
                        ),
                        location_on_asset="visible area in image",
                        confidence=0.58,
                        bounding_box=None,
                    )
                )

        if findings:
            return findings

        return [
            ImageFinding(
                defect_type="unknown",
                description=(
                    f"Image was attached for {asset_type}, but the local heuristic "
                    "could not identify a likely defect. A vision model should review it."
                ),
                location_on_asset="visible area in image",
                confidence=0.25,
            )
        ]


class MetadataImageAnalyzer(ImageAnalyzer):
    DEFECT_ALIASES = {
        "corrosion_staining": "corrosion",
    }

    def __init__(self, annotations_path: str = "data/bridge_image/annotations.csv"):
        self.annotations_path = Path(annotations_path)
        self._annotations_by_path = self._load_annotations(self.annotations_path)

    def analyze(self, image_path: str, asset_type: str) -> list[ImageFinding]:
        rows = self._find_rows(image_path)
        if not rows:
            return [
                ImageFinding(
                    defect_type="unknown",
                    description=(
                        f"No metadata annotation was found for {Path(image_path).name}. "
                        "Use the heuristic or OpenAI analyzer for unannotated images."
                    ),
                    location_on_asset="visible area in image",
                    confidence=0.2,
                )
            ]

        findings = []
        for row in rows:
            raw_defect_type = row.get("defect_type", "unknown")
            defect_type = self.DEFECT_ALIASES.get(raw_defect_type, raw_defect_type)
            findings.append(
                ImageFinding(
                    defect_type=defect_type,
                    description=(
                        f"Metadata annotation {row.get('annotation_id', 'unknown')} "
                        f"flags {raw_defect_type} on {asset_type} "
                        f"with labeled severity {row.get('severity_label', 'unknown')}."
                    ),
                    location_on_asset=(
                        row.get("component")
                        or row.get("location_on_asset")
                        or "visible area in image"
                    ),
                    confidence=0.95,
                    bounding_box=self._bounding_box(row),
                    severity_label=row.get("severity_label") or None,
                )
            )
        return findings

    def _load_annotations(
        self,
        annotations_path: Path,
    ) -> dict[str, list[dict[str, str]]]:
        if not annotations_path.exists():
            raise FileNotFoundError(
                f"Image annotation metadata not found: {annotations_path}"
            )

        annotations_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        with annotations_path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                file_path = row.get("file_path", "")
                if not file_path:
                    continue
                for key in self._path_keys(file_path):
                    annotations_by_path[key].append(row)
        return annotations_by_path

    def _find_rows(self, image_path: str) -> list[dict[str, str]]:
        for key in self._path_keys(image_path):
            rows = self._annotations_by_path.get(key)
            if rows:
                return rows
        return []

    def _path_keys(self, image_path: str) -> list[str]:
        path = Path(image_path)
        keys = [image_path, path.as_posix(), path.name]
        try:
            keys.append(str(path.resolve()))
        except OSError:
            pass
        return list(dict.fromkeys(keys))

    def _bounding_box(self, row: dict[str, str]) -> tuple[int, int, int, int] | None:
        try:
            return (
                round(float(row["x"])),
                round(float(row["y"])),
                round(float(row["width"])),
                round(float(row["height"])),
            )
        except (KeyError, TypeError, ValueError):
            return None


class OpenAIImageAnalyzer(ImageAnalyzer):
    PROMPT_PROFILES = {
        "bridge_defect_v1": (
            "Inspect this infrastructure image as a bridge defect assessor. "
            "Return only JSON with a top-level findings array. Each finding must "
            "include defect_type, severity_label, description, location_on_asset, "
            "confidence, and optional bounding_box as [x,y,width,height]. "
            "Use only these defect_type values: crack, spalling, exposed_rebar, "
            "corrosion, leak, unknown. Use only these severity_label values: "
            "none, low, moderate, high, critical. Definitions: crack means a "
            "visible linear fracture in concrete or steel; spalling means missing, "
            "flaked, broken, or delaminated concrete cover; exposed_rebar means "
            "visible reinforcing steel due to concrete loss; corrosion means rust, "
            "rust staining, or corrosion products; leak means active water, seepage, "
            "wet path, or drainage-related staining; unknown means no visible defect "
            "or insufficient image evidence. Severity guidance: critical means "
            "immediate safety concern; high means exposed rebar, loose or missing "
            "concrete, large spalling, or defects likely to affect traffic/user "
            "safety; moderate means clear cracking, corrosion staining, leak, or "
            "spalling needing scheduled repair; low means minor cosmetic defect; "
            "none means no visible defect. Do not invent defects. If uncertain, "
            "use unknown with lower confidence. Never return freeform defect labels."
        ),
        "bridge_defect_v2_strict": (
            "Inspect this infrastructure image as a bridge defect assessor. "
            "Return only JSON with a top-level findings array. Each finding must "
            "include defect_type, severity_label, description, location_on_asset, "
            "confidence, and optional bounding_box as [x,y,width,height]. "
            "Use only these defect_type values: crack, spalling, exposed_rebar, "
            "corrosion, leak, unknown. Use only these severity_label values: "
            "none, low, moderate, high, critical. Scan the whole image, including "
            "top edges, underside regions, joints, corners, and small distant patches. "
            "Bridge defects can be small or partially visible. Choose spalling when "
            "concrete is missing, flaked, broken, delaminated, or rough aggregate/voids "
            "are visible. Choose exposed_rebar when reinforcing steel or bar-like "
            "metal is visible due to concrete cover loss. Choose crack only for clear "
            "linear fractures. Choose corrosion only for rust, rust staining, or "
            "corrosion products. Choose leak only for active water, seepage, wet paths, "
            "or drainage staining. For normal expansion joints, seams, shadows, dirt, "
            "paint variation, camera artifacts, or clean concrete with no clear damage, "
            "return a single unknown finding with severity_label none. Severity guidance: "
            "critical means immediate safety concern; high means exposed rebar, loose "
            "or missing concrete, large spalling, or defects likely to affect traffic/user "
            "safety; moderate means clear cracking, corrosion staining, leak, or smaller "
            "spalling needing scheduled repair; low means minor cosmetic defect; none "
            "means no visible defect. Do not invent defects. Prefer a specific defect "
            "over unknown only when visual evidence is clear. Never return freeform labels."
        ),
        "bridge_defect_v3_spalling_verifier": (
            "Inspect this infrastructure image as a bridge defect verifier. "
            "Return only JSON with a top-level findings array. Each finding must "
            "include defect_type, severity_label, description, location_on_asset, "
            "confidence, and optional bounding_box as [x,y,width,height]. "
            "Use only these defect_type values: crack, spalling, exposed_rebar, "
            "corrosion, leak, unknown. Use only these severity_label values: "
            "none, low, moderate, high, critical. Focus especially on separating "
            "crack from spalling. Choose crack for a clear linear fracture, narrow "
            "line, joint-like split, or surface fissure when concrete material is "
            "still present. Choose spalling only when concrete cover is visibly "
            "missing, flaked, broken, delaminated, chipped away, or when exposed "
            "aggregate, voids, cavities, rough broken concrete, concrete loss, or "
            "broken edges are visible. If choosing spalling, the description must "
            "explicitly name the concrete-loss evidence. Do not choose spalling for "
            "a line, stain, seam, shadow, discoloration, efflorescence, or surface "
            "texture alone. If both crack and spalling appear, include both only "
            "when each has separate visible evidence. Prefer unknown when evidence "
            "is not visually clear. Never return freeform defect labels."
        ),
    }
    DEFECT_ALIASES = {
        "cracking": "crack",
        "fracture": "crack",
        "concrete crack": "crack",
        "spall": "spalling",
        "concrete spalling": "spalling",
        "delamination": "spalling",
        "exposed reinforcement": "exposed_rebar",
        "exposed rebar": "exposed_rebar",
        "exposed-bar": "exposed_rebar",
        "rust": "corrosion",
        "rust staining": "corrosion",
        "staining": "corrosion",
        "concrete staining": "corrosion",
        "surface discoloration": "corrosion",
        "discoloration": "corrosion",
        "water intrusion": "leak",
        "seepage": "leak",
        "water leak": "leak",
    }

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        prompt_profile: str | None = None,
        image_detail: str | None = None,
        image_tiling: str = "none",
    ):
        self.model = model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-4.1-mini")
        self.prompt_profile = (
            prompt_profile
            or os.getenv("OPENAI_IMAGE_PROMPT_PROFILE")
            or "bridge_defect_v1"
        )
        self.image_detail = image_detail or os.getenv("OPENAI_IMAGE_DETAIL") or "high"
        self.image_tiling = image_tiling
        self.client = client or self._default_client()

    def analyze(self, image_path: str, asset_type: str) -> list[ImageFinding]:
        response = self.client.invoke(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self._prompt_text(asset_type),
                        },
                        *self._image_content_parts(image_path),
                    ],
                }
            ]
        )
        return self._parse_findings(self._response_text(response), asset_type)

    def _prompt_text(self, asset_type: str) -> str:
        try:
            profile_prompt = self.PROMPT_PROFILES[self.prompt_profile]
        except KeyError as exc:
            profiles = ", ".join(sorted(self.PROMPT_PROFILES))
            raise ValueError(
                f"Unsupported OpenAI image prompt profile: {self.prompt_profile}. "
                f"Available profiles: {profiles}."
            ) from exc
        tiling_note = ""
        if self.image_tiling == "grid-2x2":
            tiling_note = (
                " The request includes the full image followed by quadrant crops; "
                "use the crops to inspect small or edge defects."
            )
        return f"{profile_prompt}{tiling_note} Asset type: {asset_type}."

    def _default_client(self) -> Any:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI image analysis requires the 'langchain-openai' package. "
                "Install requirements and retry, or use '--image-analyzer heuristic'."
            ) from exc
        return ChatOpenAI(model=self.model, temperature=0)

    def _image_data_url(self, image_path: str) -> str:
        path = Path(image_path)
        media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{media_type};base64,{encoded}"

    def _image_content_parts(self, image_path: str) -> list[dict[str, Any]]:
        parts = [self._image_part(self._image_data_url(image_path))]
        if self.image_tiling == "none":
            return parts
        if self.image_tiling == "grid-2x2":
            parts.extend(self._grid_2x2_parts(image_path))
            return parts
        raise ValueError(
            "Unsupported OpenAI image tiling mode: "
            f"{self.image_tiling}. Available modes: none, grid-2x2."
        )

    def _image_part(self, image_url: str) -> dict[str, Any]:
        return {
            "type": "image_url",
            "image_url": {
                "url": image_url,
                "detail": self.image_detail,
            },
        }

    def _grid_2x2_parts(self, image_path: str) -> list[dict[str, Any]]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI image tiling requires Pillow. Install requirements and retry, "
                "or use '--image-tiling none'."
            ) from exc

        path = Path(image_path)
        with Image.open(path) as image:
            rgb_image = image.convert("RGB")
            width, height = rgb_image.size
            crop_boxes = [
                ("top-left", (0, 0, width // 2, height // 2)),
                ("top-right", (width // 2, 0, width, height // 2)),
                ("bottom-left", (0, height // 2, width // 2, height)),
                ("bottom-right", (width // 2, height // 2, width, height)),
            ]
            parts: list[dict[str, Any]] = []
            for label, box in crop_boxes:
                buffer = BytesIO()
                rgb_image.crop(box).save(buffer, format="JPEG", quality=90)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                parts.append(
                    {
                        "type": "text",
                        "text": f"Additional high-resolution crop: {label}.",
                    }
                )
                parts.append(self._image_part(f"data:image/jpeg;base64,{encoded}"))
            return parts

    def _response_text(self, response: Any) -> str:
        if isinstance(response, str):
            return response

        content = getattr(response, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            ]
            if text_parts:
                return "\n".join(text_parts)

        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text

        try:
            return response.output[0].content[0].text
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise ValueError("OpenAI response did not contain parseable text.") from exc

    def _parse_findings(self, text: str, asset_type: str) -> list[ImageFinding]:
        try:
            payload = json.loads(self._extract_json_text(text))
        except json.JSONDecodeError:
            return [
                ImageFinding(
                    defect_type="unknown",
                    description=(
                        "OpenAI image analysis returned non-JSON output and could "
                        f"not be parsed into structured findings for {asset_type}."
                    ),
                    location_on_asset="visible area in image",
                    confidence=0.2,
                )
            ]
        raw_findings = payload if isinstance(payload, list) else payload.get("findings", [])
        findings = []

        for raw in raw_findings:
            if not isinstance(raw, dict):
                continue
            bounding_box = raw.get("bounding_box")
            findings.append(
                ImageFinding(
                    defect_type=self._normalize_defect_type(
                        str(raw.get("defect_type", "unknown"))
                    ),
                    description=str(
                        raw.get(
                            "description",
                            f"OpenAI image analysis returned a finding for {asset_type}.",
                        )
                    ),
                    location_on_asset=str(raw.get("location_on_asset", "unspecified")),
                    confidence=self._parse_confidence(raw.get("confidence", 0.5)),
                    bounding_box=tuple(bounding_box) if bounding_box else None,
                    severity_label=self._normalize_severity_label(
                        str(raw.get("severity_label", ""))
                    ),
                )
            )

        if findings:
            return findings

        return [
            ImageFinding(
                defect_type="unknown",
                description=f"OpenAI image analysis found no specific defect on {asset_type}.",
                location_on_asset="visible area in image",
                confidence=0.3,
            )
        ]

    def _extract_json_text(self, text: str) -> str:
        stripped = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
        if fenced:
            return fenced.group(1)

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return stripped[start : end + 1]

        return stripped

    def _normalize_defect_type(self, defect_type: str) -> str:
        normalized = defect_type.strip().lower().replace("_", " ").replace("-", " ")
        if normalized in {"crack", "spalling", "corrosion", "leak", "unknown"}:
            return normalized
        if normalized == "exposed rebar":
            return "exposed_rebar"
        return self.DEFECT_ALIASES.get(normalized, defect_type)

    def _normalize_severity_label(self, severity_label: str) -> str | None:
        normalized = severity_label.strip().lower().replace("_", " ").replace("-", " ")
        if not normalized:
            return None
        if normalized == "medium":
            return "moderate"
        if normalized in {"none", "low", "moderate", "high", "critical"}:
            return normalized
        return None

    def _parse_confidence(self, confidence: Any) -> float:
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            normalized = str(confidence).strip().lower()
            value = {
                "very low": 0.2,
                "low": 0.35,
                "medium": 0.55,
                "moderate": 0.55,
                "high": 0.8,
                "very high": 0.92,
            }.get(normalized, 0.5)
        return max(0.0, min(1.0, value))


class RoboflowImageAnalyzer(ImageAnalyzer):
    DEFAULT_DEFECT_ALIASES = {
        "cracking": "crack",
        "crack": "crack",
        "spall": "spalling",
        "spalling": "spalling",
        "delamination": "spalling",
        "exposed reinforcement": "exposed_rebar",
        "exposed bar": "exposed_rebar",
        "exposed rebar": "exposed_rebar",
        "rebar exposure": "exposed_rebar",
        "rebar exposed": "exposed_rebar",
        "exposed_rebar": "exposed_rebar",
        "rebar": "exposed_rebar",
        "rust": "corrosion",
        "stain": "corrosion",
        "efflorescence": "leak",
        "rust staining": "corrosion",
        "corrosion staining": "corrosion",
        "corrosion_staining": "corrosion",
        "corrosion": "corrosion",
        "water leak": "leak",
        "water_leak": "leak",
        "seepage": "leak",
        "leak": "leak",
        "normal": "unknown",
        "no defect": "unknown",
        "no_defect": "unknown",
        "none": "unknown",
        "all": "unknown",
        "unknown": "unknown",
    }
    CLASS_MAPPING_PROFILES = {
        "default": {},
        "bridge_dataset": {
            "efflorescence": "corrosion",
        },
    }
    SEVERITY_ALIASES = {
        "none": "none",
        "low": "low",
        "moderate": "moderate",
        "medium": "moderate",
        "high": "high",
        "critical": "critical",
    }
    DEFAULT_SEVERITY_BY_DEFECT = {
        "unknown": "none",
        "crack": "moderate",
        "spalling": "high",
        "exposed_rebar": "high",
        "corrosion": "moderate",
        "leak": "moderate",
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_id: str | None = None,
        model_version: str | None = None,
        api_url: str | None = None,
        confidence_threshold: float = 0.25,
        backend: str | None = None,
        class_mapping_profile: str | None = None,
        tiling: str = "none",
        class_confidence_thresholds: dict[str, float] | str | None = None,
        inference_confidence: float | None = None,
        inference_iou_threshold: float | None = None,
        client: Any | None = None,
    ):
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        self.api_key = api_key or os.getenv("ROBOFLOW_API_KEY")
        self.model_id = model_id or os.getenv("ROBOFLOW_MODEL_ID")
        self.model_version = model_version or os.getenv("ROBOFLOW_MODEL_VERSION")
        self.api_url = (
            api_url
            if api_url is not None
            else (None if model_id is not None else os.getenv("ROBOFLOW_API_URL"))
        )
        self.confidence_threshold = confidence_threshold
        self.inference_confidence = self._configured_inference_confidence(
            inference_confidence
        )
        self.inference_iou_threshold = self._configured_inference_iou_threshold(
            inference_iou_threshold
        )
        self.backend = backend or os.getenv("ROBOFLOW_BACKEND", "auto")
        self.class_mapping_profile = (
            class_mapping_profile
            or os.getenv("ROBOFLOW_CLASS_MAPPING_PROFILE")
            or "default"
        )
        self.defect_aliases = self._defect_aliases_for_profile(
            self.class_mapping_profile
        )
        self.tiling = tiling
        self.class_confidence_thresholds = self._parse_class_confidence_thresholds(
            class_confidence_thresholds
            if class_confidence_thresholds is not None
            else os.getenv("ROBOFLOW_CLASS_THRESHOLDS")
        )
        self._inference_model = None
        self.client = client or self._default_client

    def analyze(self, image_path: str, asset_type: str) -> list[ImageFinding]:
        findings: list[ImageFinding] = []
        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        try:
            if self.tiling == "none":
                image_variants = [("full image", image_path, 0, 0)]
            elif self.tiling == "grid-2x2":
                temp_dir = tempfile.TemporaryDirectory()
                image_variants = [
                    ("full image", image_path, 0, 0),
                    *self._grid_2x2_variants(image_path, temp_dir.name),
                ]
            else:
                raise ValueError(
                    f"Unsupported Roboflow tiling mode: {self.tiling}. "
                    "Available modes: none, grid-2x2."
                )

            for variant_label, variant_path, offset_x, offset_y in image_variants:
                payload = self.client(variant_path)
                predictions = self._extract_predictions(payload)
                for prediction in predictions:
                    if not isinstance(prediction, dict):
                        continue
                    finding = self._prediction_to_finding(
                        prediction,
                        asset_type,
                        variant_label=variant_label,
                        offset_x=offset_x,
                        offset_y=offset_y,
                    )
                    if finding is not None and self._passes_confidence_threshold(finding):
                        findings.append(finding)
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

        findings = self._deduplicate_findings(findings)

        if findings:
            return findings

        return [
            ImageFinding(
                defect_type="unknown",
                description=(
                    f"Roboflow bridge defect model found no prediction above "
                    f"{self._threshold_summary()} confidence for {asset_type} "
                    f"using {self.tiling} tiling."
                ),
                location_on_asset="visible area in image",
                confidence=0.3,
                severity_label="none",
            )
        ]

    def _default_client(self, image_path: str) -> dict[str, Any]:
        if self.backend not in {"auto", "http", "inference"}:
            raise ValueError(
                f"Unsupported Roboflow backend: {self.backend}. "
                "Available backends: auto, inference, http."
            )
        if self.backend in {"auto", "inference"}:
            try:
                return self._inference_sdk_client(image_path)
            except ImportError:
                if self.backend == "inference":
                    raise RuntimeError(
                        "Roboflow inference backend requires the 'inference' package. "
                        "Install requirements or set ROBOFLOW_BACKEND=http."
                    )
            except Exception:
                if self.backend == "inference":
                    raise

        return self._http_client(image_path)

    def _inference_sdk_client(self, image_path: str) -> dict[str, Any]:
        try:
            from inference import get_model
        except ImportError:
            raise

        model_id = self._configured_model_path()
        if not model_id:
            raise RuntimeError(
                "Roboflow inference SDK requires ROBOFLOW_MODEL_ID with a version "
                "suffix like 'model-id/1', or ROBOFLOW_MODEL_VERSION."
            )
        if self._inference_model is None:
            self._inference_model = get_model(model_id=model_id)
        result = self._inference_model.infer(
            image=image_path,
            confidence=self.inference_confidence,
            iou_threshold=self.inference_iou_threshold,
        )
        return {"predictions": self._extract_predictions(result)}

    def _http_client(self, image_path: str) -> dict[str, Any]:
        image_bytes = Path(image_path).read_bytes()
        errors: list[str] = []
        for endpoint in self._candidate_endpoints():
            endpoint = self._append_inference_parameters(endpoint)
            requests = [
                Request(
                    endpoint,
                    data=image_bytes,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "User-Agent": "infrastructure-ai-agent/0.1",
                    },
                    method="POST",
                ),
                Request(
                    endpoint,
                    data=base64.b64encode(image_bytes),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "User-Agent": "infrastructure-ai-agent/0.1",
                    },
                    method="POST",
                ),
            ]
            for request in requests:
                try:
                    with urlopen(request, timeout=60) as response:
                        return json.loads(response.read().decode("utf-8"))
                except HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="replace")
                    errors.append(
                        f"{self._redact_api_key(endpoint)} HTTP {exc.code}: {detail}"
                    )
                except (OSError, URLError) as exc:
                    errors.append(f"{self._redact_api_key(endpoint)}: {exc}")
                except json.JSONDecodeError as exc:
                    errors.append(
                        f"{self._redact_api_key(endpoint)} non-JSON output: {exc}"
                    )

        raise RuntimeError(
            "Roboflow inference failed after trying raw-image and base64 request "
            f"formats: {'; '.join(errors)}"
        )

    def _extract_predictions(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            predictions = payload.get("predictions", [])
        elif isinstance(payload, list):
            if payload and self._has_predictions(payload[0]):
                predictions = getattr(payload[0], "predictions", None)
                if predictions is None and isinstance(payload[0], dict):
                    predictions = payload[0].get("predictions", [])
            else:
                predictions = payload
        else:
            predictions = getattr(payload, "predictions", [])

        return [self._prediction_to_dict(prediction) for prediction in predictions]

    def _has_predictions(self, value: Any) -> bool:
        return (
            isinstance(value, dict)
            and "predictions" in value
            or hasattr(value, "predictions")
        )

    def _prediction_to_dict(self, prediction: Any) -> dict[str, Any]:
        if isinstance(prediction, dict):
            return prediction
        keys = [
            "class",
            "class_name",
            "label",
            "confidence",
            "x",
            "y",
            "width",
            "height",
            "bounding_box",
        ]
        return {
            key: getattr(prediction, key)
            for key in keys
            if hasattr(prediction, key)
        }

    def _endpoint(self) -> str:
        return self._candidate_endpoints()[0]

    def _candidate_endpoints(self) -> list[str]:
        if self.api_url:
            return [
                self._append_api_key(url)
                for url in self._normalize_api_url_candidates(self.api_url)
            ]
        if not self.api_key:
            raise RuntimeError(
                "Roboflow image analysis requires ROBOFLOW_API_KEY or "
                "roboflow_api_key."
            )
        if not self.model_id:
            raise RuntimeError(
                "Roboflow image analysis requires ROBOFLOW_MODEL_ID or "
                "ROBOFLOW_API_URL."
            )
        model_path = self.model_id.strip("/")
        if not model_path.rsplit("/", 1)[-1].isdigit():
            if not self.model_version:
                raise RuntimeError(
                    "ROBOFLOW_MODEL_ID must include a version suffix like "
                    "'model-id/1', or ROBOFLOW_MODEL_VERSION must be set."
            )
            model_path = f"{model_path}/{self.model_version}"
        url = f"https://detect.roboflow.com/{model_path}"
        return [self._append_api_key(url)]

    def _normalize_api_url_candidates(self, api_url: str) -> list[str]:
        parsed = urlparse(api_url)
        if parsed.netloc == "serverless.roboflow.com" and parsed.path in {"", "/"}:
            model_path = self._configured_model_path()
            if model_path:
                return [f"https://serverless.roboflow.com/{model_path}"]
            return [api_url]

        if parsed.netloc != "universe.roboflow.com":
            return [api_url]

        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return [api_url]

        project_slug = path_parts[-1]
        version = self._configured_version()
        if not version:
            return [api_url]

        candidates = [f"https://detect.roboflow.com/{project_slug}/{version}"]
        if len(path_parts) >= 2:
            workspace_slug = path_parts[-2]
            candidates.append(
                f"https://detect.roboflow.com/{workspace_slug}/{project_slug}/{version}"
            )
        return candidates

    def _configured_model_path(self) -> str | None:
        if not self.model_id:
            return None
        model_path = self.model_id.strip("/")
        if model_path.rsplit("/", 1)[-1].isdigit():
            return model_path
        if self.model_version:
            return f"{model_path}/{self.model_version}"
        return None

    def _configured_version(self) -> str | None:
        if self.model_version:
            return str(self.model_version).strip("/")
        if self.model_id:
            maybe_version = self.model_id.strip("/").rsplit("/", 1)[-1]
            if maybe_version.isdigit():
                return maybe_version
        return None

    def _append_api_key(self, url: str) -> str:
        if "api_key=" in url:
            return url
        if not self.api_key:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode({'api_key': self.api_key})}"

    def _append_inference_parameters(self, url: str) -> str:
        parameters = {
            "confidence": self.inference_confidence,
            "overlap": self.inference_iou_threshold,
        }
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode(parameters)}"

    def _redact_api_key(self, url: str) -> str:
        return re.sub(r"api_key=[^&]+", "api_key=<redacted>", url)

    def _prediction_to_finding(
        self,
        prediction: dict[str, Any],
        asset_type: str,
        *,
        variant_label: str = "full image",
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> ImageFinding | None:
        raw_class = str(
            prediction.get("class")
            or prediction.get("class_name")
            or prediction.get("label")
            or "unknown"
        )
        defect_type = self._normalize_defect_type(raw_class)
        severity_label = self._normalize_severity_label(raw_class) or (
            self.DEFAULT_SEVERITY_BY_DEFECT.get(defect_type)
        )
        confidence = self._parse_confidence(prediction.get("confidence", 0.5))
        bounding_box = self._bounding_box(prediction)
        if bounding_box and (offset_x or offset_y):
            x, y, width, height = bounding_box
            bounding_box = (x + offset_x, y + offset_y, width, height)
        return ImageFinding(
            defect_type=defect_type,
            description=(
                f"Roboflow model detected {raw_class} on {asset_type} "
                f"with {confidence:.2f} confidence from {variant_label}."
            ),
            location_on_asset=str(
                prediction.get("location_on_asset")
                or prediction.get("region")
                or "detected region"
            ),
            confidence=confidence,
            bounding_box=bounding_box,
            severity_label=severity_label,
        )

    def _grid_2x2_variants(
        self,
        image_path: str,
        output_dir: str,
    ) -> list[tuple[str, str, int, int]]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "Roboflow tiling requires Pillow. Install requirements and retry, "
                "or use '--roboflow-tiling none'."
            ) from exc

        source_path = Path(image_path)
        with Image.open(source_path) as image:
            rgb_image = image.convert("RGB")
            width, height = rgb_image.size
            crop_specs = [
                ("top-left tile", (0, 0, width // 2, height // 2)),
                ("top-right tile", (width // 2, 0, width, height // 2)),
                ("bottom-left tile", (0, height // 2, width // 2, height)),
                ("bottom-right tile", (width // 2, height // 2, width, height)),
            ]
            variants = []
            for index, (label, box) in enumerate(crop_specs, start=1):
                left, top, right, bottom = box
                tile_path = Path(output_dir) / f"{source_path.stem}_tile_{index}.jpg"
                rgb_image.crop(box).save(tile_path, format="JPEG", quality=92)
                variants.append((label, str(tile_path), left, top))
            return variants

    def _deduplicate_findings(self, findings: list[ImageFinding]) -> list[ImageFinding]:
        kept: list[ImageFinding] = []
        for finding in sorted(findings, key=lambda item: item.confidence, reverse=True):
            duplicate = False
            for existing in kept:
                if finding.defect_type != existing.defect_type:
                    continue
                if not finding.bounding_box or not existing.bounding_box:
                    continue
                if self._box_iou(finding.bounding_box, existing.bounding_box) >= 0.5:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(finding)
        return kept

    def _passes_confidence_threshold(self, finding: ImageFinding) -> bool:
        threshold = self.class_confidence_thresholds.get(
            finding.defect_type,
            self.confidence_threshold,
        )
        return finding.confidence >= threshold

    def _threshold_summary(self) -> str:
        if not self.class_confidence_thresholds:
            return f"{self.confidence_threshold:.2f}"
        class_thresholds = ", ".join(
            f"{defect_type}={threshold:.2f}"
            for defect_type, threshold in sorted(self.class_confidence_thresholds.items())
        )
        return f"{self.confidence_threshold:.2f} default ({class_thresholds})"

    def _parse_class_confidence_thresholds(
        self,
        value: dict[str, float] | str | None,
    ) -> dict[str, float]:
        if value is None:
            return {}
        if isinstance(value, dict):
            raw_items = value.items()
        else:
            raw_items = []
            for item in value.split(","):
                stripped = item.strip()
                if not stripped:
                    continue
                if "=" not in stripped:
                    raise ValueError(
                        "Roboflow class thresholds must use defect=value pairs, "
                        "for example 'spalling=0.1,corrosion=0.75'."
                    )
                raw_class, raw_threshold = stripped.split("=", 1)
                raw_items.append((raw_class.strip(), raw_threshold.strip()))

        thresholds = {}
        for raw_class, raw_threshold in raw_items:
            defect_type = self._normalize_defect_type(str(raw_class))
            if defect_type == "unknown":
                raise ValueError(
                    f"Unsupported Roboflow class threshold defect: {raw_class}."
                )
            try:
                threshold = float(raw_threshold)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid Roboflow class threshold for {raw_class}: {raw_threshold}."
                ) from exc
            if threshold < 0 or threshold > 1:
                raise ValueError("Roboflow class thresholds must be between 0 and 1.")
            thresholds[defect_type] = threshold
        return thresholds

    def _box_iou(
        self,
        left: tuple[int, int, int, int],
        right: tuple[int, int, int, int],
    ) -> float:
        left_x, left_y, left_width, left_height = left
        right_x, right_y, right_width, right_height = right
        intersection_x1 = max(left_x, right_x)
        intersection_y1 = max(left_y, right_y)
        intersection_x2 = min(left_x + left_width, right_x + right_width)
        intersection_y2 = min(left_y + left_height, right_y + right_height)
        intersection_width = max(0, intersection_x2 - intersection_x1)
        intersection_height = max(0, intersection_y2 - intersection_y1)
        intersection_area = intersection_width * intersection_height
        union_area = (
            left_width * left_height
            + right_width * right_height
            - intersection_area
        )
        if union_area <= 0:
            return 0.0
        return intersection_area / union_area

    def _bounding_box(
        self,
        prediction: dict[str, Any],
    ) -> tuple[int, int, int, int] | None:
        if isinstance(prediction.get("bounding_box"), list):
            box = prediction["bounding_box"]
            if len(box) == 4:
                return tuple(round(float(value)) for value in box)  # type: ignore[return-value]

        try:
            width = float(prediction["width"])
            height = float(prediction["height"])
            center_x = float(prediction["x"])
            center_y = float(prediction["y"])
            return (
                round(center_x - width / 2),
                round(center_y - height / 2),
                round(width),
                round(height),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _normalize_defect_type(self, raw_class: str) -> str:
        normalized = self._normalize_label(raw_class)
        if normalized in self.defect_aliases:
            return self.defect_aliases[normalized]
        for token in self._class_tokens(raw_class):
            if token in self.defect_aliases:
                return self.defect_aliases[token]
        return "unknown"

    def _defect_aliases_for_profile(self, profile: str) -> dict[str, str]:
        try:
            overrides = self.CLASS_MAPPING_PROFILES[profile]
        except KeyError as exc:
            profiles = ", ".join(sorted(self.CLASS_MAPPING_PROFILES))
            raise ValueError(
                f"Unsupported Roboflow class mapping profile: {profile}. "
                f"Available profiles: {profiles}."
            ) from exc
        return {**self.DEFAULT_DEFECT_ALIASES, **overrides}

    def _normalize_severity_label(self, raw_class: str) -> str | None:
        normalized = self._normalize_label(raw_class)
        if normalized in self.SEVERITY_ALIASES:
            return self.SEVERITY_ALIASES[normalized]
        for token in self._class_tokens(raw_class):
            if token in self.SEVERITY_ALIASES:
                return self.SEVERITY_ALIASES[token]
        return None

    def _class_tokens(self, raw_class: str) -> list[str]:
        normalized = self._normalize_label(raw_class)
        tokens = re.split(r"\s+", normalized)
        joined_pairs = [
            " ".join(tokens[index : index + 2])
            for index in range(max(0, len(tokens) - 1))
        ]
        return [normalized, *tokens, *joined_pairs]

    def _normalize_label(self, value: str) -> str:
        return value.strip().lower().replace("_", " ").replace("-", " ")

    def _parse_confidence(self, confidence: Any) -> float:
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            value = 0.5
        return max(0.0, min(1.0, value))

    def _configured_inference_confidence(self, value: float | None) -> float:
        if value is None:
            raw_value = os.getenv("ROBOFLOW_INFERENCE_CONFIDENCE")
            if raw_value is not None:
                value = float(raw_value)
        if value is None:
            value = self.confidence_threshold
        return self._bounded_float(value, "Roboflow inference confidence")

    def _configured_inference_iou_threshold(self, value: float | None) -> float:
        if value is None:
            raw_value = os.getenv("ROBOFLOW_INFERENCE_IOU_THRESHOLD")
            if raw_value is not None:
                value = float(raw_value)
        if value is None:
            value = 0.3
        return self._bounded_float(value, "Roboflow inference IoU threshold")

    def _bounded_float(self, value: float, label: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a number between 0 and 1.") from exc
        if parsed < 0 or parsed > 1:
            raise ValueError(f"{label} must be between 0 and 1.")
        return parsed


class VerifiedImageAnalyzer(ImageAnalyzer):
    def __init__(
        self,
        base_analyzer: ImageAnalyzer,
        verifier: ImageAnalyzer,
        *,
        verification_confidence_threshold: float = 0.55,
    ):
        self.base_analyzer = base_analyzer
        self.verifier = verifier
        self.verification_confidence_threshold = verification_confidence_threshold

    def analyze(self, image_path: str, asset_type: str) -> list[ImageFinding]:
        base_findings = self.base_analyzer.analyze(image_path, asset_type)
        if not self._needs_verification(base_findings):
            return base_findings

        verifier_findings = self.verifier.analyze(image_path, asset_type)
        accepted = [
            self._verified_finding(finding, base_findings)
            for finding in verifier_findings
            if self._accepts_verifier_finding(finding)
        ]
        if not accepted:
            return base_findings

        return self._merge_findings(base_findings, accepted) or base_findings

    def _needs_verification(self, findings: list[ImageFinding]) -> bool:
        if not findings:
            return True

        known_findings = [
            finding for finding in findings if finding.defect_type in KNOWN_DEFECT_TYPES
        ]
        if not known_findings:
            return True

        defect_types = {finding.defect_type for finding in known_findings}

        if defect_types == {"crack"}:
            return True
        if "crack" in defect_types and "spalling" not in defect_types:
            return True
        return False

    def _accepts_verifier_finding(self, finding: ImageFinding) -> bool:
        if finding.defect_type not in KNOWN_DEFECT_TYPES:
            return False
        if finding.confidence < self.verification_confidence_threshold:
            return False
        if finding.defect_type == "spalling":
            return self._has_spalling_evidence(finding.description)
        return True

    def _has_spalling_evidence(self, description: str) -> bool:
        normalized = description.lower().replace("-", " ")
        evidence_terms = {
            "missing concrete",
            "missing cover",
            "concrete cover",
            "concrete loss",
            "loss of concrete",
            "material loss",
            "flaked",
            "flaking",
            "broken concrete",
            "broken edge",
            "chipped",
            "delaminated",
            "delamination",
            "exposed aggregate",
            "aggregate",
            "void",
            "cavity",
            "rough broken",
        }
        return any(term in normalized for term in evidence_terms)

    def _verified_finding(
        self,
        finding: ImageFinding,
        base_findings: list[ImageFinding],
    ) -> ImageFinding:
        base_summary = ", ".join(
            f"{item.defect_type}:{item.confidence:.2f}" for item in base_findings[:4]
        )
        severity_label = finding.severity_label
        if finding.defect_type == "spalling" and self._has_spalling_evidence(
            finding.description
        ):
            severity_label = "high"
        return ImageFinding(
            defect_type=finding.defect_type,
            description=(
                "OpenAI verifier reviewed an ambiguous detector result "
                f"({base_summary or 'no base findings'}) and selected "
                f"{finding.defect_type}. {finding.description}"
            ),
            location_on_asset=finding.location_on_asset,
            confidence=finding.confidence,
            bounding_box=finding.bounding_box,
            severity_label=severity_label,
        )

    def _merge_findings(
        self,
        base_findings: list[ImageFinding],
        verified_findings: list[ImageFinding],
    ) -> list[ImageFinding]:
        non_unknown_base = [
            finding for finding in base_findings if finding.defect_type != "unknown"
        ]
        if not non_unknown_base:
            return verified_findings

        merged = verified_findings.copy()
        verified_types = {finding.defect_type for finding in verified_findings}
        for finding in non_unknown_base:
            if finding.defect_type in verified_types and finding.confidence < 0.5:
                continue
            if (
                finding.defect_type == "crack"
                and "spalling" in verified_types
                and finding.confidence < 0.85
            ):
                continue
            merged.append(finding)
        return merged


def build_image_analyzer(
    mode: str,
    *,
    annotations_path: str = "data/bridge_image/annotations.csv",
    image_prompt_profile: str | None = None,
    image_detail: str | None = None,
    image_tiling: str = "none",
    roboflow_confidence_threshold: float = 0.25,
    roboflow_backend: str | None = None,
    roboflow_class_mapping_profile: str | None = None,
    roboflow_tiling: str = "none",
    roboflow_class_thresholds: dict[str, float] | str | None = None,
    roboflow_inference_confidence: float | None = None,
    roboflow_inference_iou_threshold: float | None = None,
    vision_verifier: str = "none",
    verification_confidence_threshold: float = 0.55,
    verifier_prompt_profile: str | None = None,
) -> ImageAnalyzer:
    if mode == "heuristic":
        analyzer: ImageAnalyzer = HeuristicImageAnalyzer()
    elif mode == "metadata":
        analyzer = MetadataImageAnalyzer(annotations_path)
    elif mode == "openai":
        analyzer = OpenAIImageAnalyzer(
            prompt_profile=image_prompt_profile,
            image_detail=image_detail,
            image_tiling=image_tiling,
        )
    elif mode == "roboflow":
        analyzer = RoboflowImageAnalyzer(
            confidence_threshold=roboflow_confidence_threshold,
            backend=roboflow_backend,
            class_mapping_profile=roboflow_class_mapping_profile,
            tiling=roboflow_tiling,
            class_confidence_thresholds=roboflow_class_thresholds,
            inference_confidence=roboflow_inference_confidence,
            inference_iou_threshold=roboflow_inference_iou_threshold,
        )
    else:
        raise ValueError(f"Unsupported image analyzer mode: {mode}")

    if vision_verifier == "none" or mode == "openai":
        return analyzer
    if vision_verifier == "openai":
        return VerifiedImageAnalyzer(
            analyzer,
            OpenAIImageAnalyzer(
                prompt_profile=(
                    verifier_prompt_profile
                    or image_prompt_profile
                    or "bridge_defect_v2_strict"
                ),
                image_detail=image_detail,
                image_tiling=image_tiling,
            ),
            verification_confidence_threshold=verification_confidence_threshold,
        )
    raise ValueError(f"Unsupported vision verifier mode: {vision_verifier}")
