"""Кастомный компонент Langflow: агент-диспетчер РЗА с жёсткой привязкой к базе знаний."""

from langflow.custom import Component
from langflow.io import Output, MessageTextInput, DataInput
from langflow.schema.message import Message
from langchain_core.language_models import BaseLanguageModel
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage


SYSTEM_PROMPT = (
    "Ты — ведущий инженер-проектировщик РЗА. Твоя задача — строго анализировать "
    "нормативную базу и ТЗ.\n"
    "ПРАВИЛО ИНСТРУМЕНТА: При упоминании любых нормативных документов (Приказы "
    "Минэнерго, ПУЭ, ГОСТ, СТО) или названий проектов, ты обязан выполнить поиск "
    "через инструмент `search_rza_knowledge_base`.\n"
    "ПРАВИЛО ИСТИНЫ: Отвечай на основе ТОЛЬКО тех фрагментов документов, которые "
    "вернул инструмент поиска. Если инструмент вернул 'Ничего не найдено' или "
    "в предоставленном тексте нет ответа на вопрос, ты обязан прямо ответить: "
    "'В локальной базе знаний проекта rza_rag запрашиваемые сведения по данному "
    "документу отсутствуют.' Тебе СТРОГО ЗАПРЕЩЕНО выдумывать пункты, номера "
    "стандартов, защит или использовать общие знания из интернета, если они не "
    "подтверждены в тексте инструмента поиска!"
)


class RzaAgentComponent(Component):
    display_name = "Кастомный Агент РЗА"
    description = "Главный диспетчер: строго ориентирован на контекст документов и нормативной базы."
    icon = "bot"

    inputs = [
        DataInput(
            name="llm",
            display_name="Language Model",
            input_types=["BaseLanguageModel", "ChatOpenAI"],
            required=True,
        ),
        DataInput(
            name="rza_tool",
            display_name="Tools",
            input_types=["Tool"],
            required=True,
        ),
        DataInput(
            name="chat_history_input",
            display_name="Chat History (Messages)",
            input_types=["Message", "Data"],
            is_list=True,
            required=False,
        ),
        MessageTextInput(
            name="user_input",
            display_name="Input (User Query)",
        ),
    ]

    outputs = [
        Output(
            name="agent_response",
            display_name="Response",
            type=Message,
            method="run_agent",
        ),
    ]

    def run_agent(self) -> Message:
        actual_tool = self.rza_tool
        if hasattr(actual_tool, "value"):
            actual_tool = actual_tool.value
        if hasattr(actual_tool, "rza_tool"):
            actual_tool = actual_tool.rza_tool

        actual_llm = self.llm
        if hasattr(actual_llm, "value"):
            actual_llm = actual_llm.value

        tools = [actual_tool]

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        langchain_history = []
        if self.chat_history_input:
            history_list = (
                self.chat_history_input
                if isinstance(self.chat_history_input, list)
                else [self.chat_history_input]
            )
            for msg in history_list:
                try:
                    text = ""
                    sender = "user"
                    if isinstance(msg, dict):
                        text = (
                            msg.get("text")
                            or msg.get("message")
                            or msg.get("data", {}).get("text", "")
                        )
                        sender = str(msg.get("sender", "user")).lower()
                    else:
                        text = getattr(msg, "text", "") or getattr(msg, "message", "")
                        if not text and hasattr(msg, "data"):
                            text = (
                                msg.data.get("text", "")
                                if isinstance(msg.data, dict)
                                else getattr(msg.data, "text", "")
                            )
                        sender = str(getattr(msg, "sender", "user")).lower()

                    if text:
                        if "user" in sender or "human" in sender:
                            langchain_history.append(HumanMessage(content=str(text)))
                        else:
                            langchain_history.append(AIMessage(content=str(text)))
                except Exception:
                    continue

        try:
            agent = create_tool_calling_agent(actual_llm, tools, prompt)
            agent_executor = AgentExecutor(
                agent=agent, tools=tools, verbose=True, handle_parsing_errors=True
            )
            response = agent_executor.invoke({
                "input": self.user_input,
                "chat_history": langchain_history,
            })
            final_text = str(response["output"])
        except Exception as e:
            final_text = f"Ошибка Агента в рантайме: {str(e)}"

        return Message(text=final_text)
