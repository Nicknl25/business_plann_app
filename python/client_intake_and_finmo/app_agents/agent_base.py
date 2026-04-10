from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Dict

from .openai_client import call_agent_with_schema
from .prompt_loader import load_prompt
from .schema_loader import load_schema


@dataclass(slots=True)
class BaseAppAgent:
  agent_name: str
  schema_file: str
  expertise_brief: str
  prompt_file: str

  def output_schema(self) -> Dict[str, Any]:
    return load_schema(self.schema_file)

  def build_system_brief(self) -> str:
    prompt_text = load_prompt(self.prompt_file)
    return "\n\n".join(part for part in (self.expertise_brief.strip(), prompt_text.strip()) if part.strip())

  def build_request(self, *, shared_context: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    payload = {
      "agent_name": self.agent_name,
      "system_brief": self.build_system_brief(),
      "shared_context": copy.deepcopy(shared_context or {}),
    }
    payload.update(self._extra_request_fields(**kwargs))
    return payload

  def _extra_request_fields(self, **kwargs: Any) -> Dict[str, Any]:
    return dict(kwargs or {})

  def build_user_prompt(self, *, shared_context: Dict[str, Any], **kwargs: Any) -> str:
    request_payload = self.build_request(shared_context=shared_context, **kwargs)
    return json.dumps(request_payload, ensure_ascii=False)

  def generate(self, *, shared_context: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    schema_wrapper = self.output_schema()
    schema = schema_wrapper.get("schema") if isinstance(schema_wrapper.get("schema"), dict) else schema_wrapper
    return call_agent_with_schema(
      agent_name=self.agent_name,
      system_prompt=self.build_system_brief(),
      user_prompt=self.build_user_prompt(shared_context=shared_context, **kwargs),
      schema_name=self.agent_name,
      schema=schema,
    )
