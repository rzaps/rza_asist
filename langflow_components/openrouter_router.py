"""Кастомный компонент Langflow: прозрачный авто-роутер OpenRouter."""

from langflow.custom import Component
from langflow.io import Output, SecretStrInput, MessageTextInput
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseLanguageModel


class TransparentRouterComponent(Component):
    display_name = "Прозрачный Авто-Роутер"
    description = "Подключает OpenRouter/free как полноценную модель для Агента."
    icon = "eye"

    inputs = [
        SecretStrInput(
            name="api_key", display_name="OpenRouter API Key", required=True
        ),
        MessageTextInput(
            name="model_name",
            display_name="Модель",
            value="openrouter/auto",
        ),
    ]

    outputs = [
        Output(
            name="model_output",
            display_name="Model",
            type=BaseLanguageModel,
            method="build_model",
        ),
    ]

    def build_model(self) -> BaseLanguageModel:
        return ChatOpenAI(
            openai_api_key=self.api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            model_name=self.model_name,
            temperature=0.0,
            default_headers={
                "HTTP-Referer": "https://langflow.org",
                "X-Title": "RZA Agent",
            },
        )
