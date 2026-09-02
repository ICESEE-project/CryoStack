# The CryoStack LLM provider contract (PASS 4, task 8)

CryoStack is **provider-agnostic**. Claude, GPT, a local model, or a
rule-based stub are all wired the same way. This document is the contract.

## The whole interface

```python
class LLMClient(Protocol):                       # cryostack_src/agents/llm.py
    def complete(self, *, system: str,
                 messages: list[LLMMessage],
                 tools: list[dict]) -> LLMResponse: ...
```

* `LLMMessage(role, content, name="")` — `role ∈ {"user","assistant","tool"}`.
* `tools` — a list of **plain dicts**: `{name, description, permission,
  read_only, requires_confirmation, scientific_effect, parameters}`. Produced
  by `ToolRegistry.describe(ctx=ctx)`. **Never a callable, path, socket,
  bridge, or credential** — enforced by `assert_declarative_tools`
  (`llm_adapters.py`), which `BaseAdapter.complete` runs on every call.
* `LLMResponse(text="", tool_calls=())` — free text and/or
  `LLMToolCall(name, arguments)`. `name` is matched against the registry by
  `ToolRegistry.invoke`; an unknown name returns an error `ToolResult`, it is
  not executed.
* Optional: `observe_tool_result(name, value)` — a stateful adapter may
  implement this to thread a tool result (e.g. the plan dict) into its next
  turn. Purely advisory; the assistant calls it if present.

That is the entire surface. A provider transforms *user intent* into
*structured tool requests*. It does nothing else.

## What a provider never receives

| Not passed | Why |
|---|---|
| a shell / SSH command string | there is no tool that takes one |
| an env dict | there is no tool that takes one |
| a filesystem path | tools return names/ids; `assert_declarative_tools` would reject a `Path` |
| `RemoteBridge` / `CloudBridge` / any submitter | not in `tools`; not importable from a tool module (`policy.PROHIBITED_SYMBOLS`) |
| an approval or execute capability | the assistant context is hard-capped at `Permission.PLAN`; no approve/execute tool exists |
| an API key, token, or secret | CryoStack never sets one; the provider reads its own from its own env |

## What stays CryoStack-side, always

`RunAssistant` loop · `ToolRegistry` permission ceiling · `planning`
(RunPlan + digest) · `validate_run_plan` (B4 / Basic-mode / preflight) ·
`approval` (digest-bound, human-only) · `execution` (dry-run coordinator) ·
`agent_execution.RemoteSubmitBackend` (B3/B4/preflight composition).

None of these import or depend on a provider. Swapping the provider changes
*how a sentence becomes a tool call* — nothing about what a tool call is
allowed to do.

## Implementing a real provider

1. Subclass `BaseAdapter` (so `assert_declarative_tools` runs for free).
2. In `_complete`: translate `tools` to the provider's function/tool schema,
   `messages`+`system` to its message shape, call the provider, map the
   response back to `text` + `LLMToolCall`s.
3. Read the API key from **your** environment. Never log `messages` (they can
   contain a user's workspace details) or the key.
4. Ship it in your **own** integration package. Do not add an SDK dependency
   to `cryostack_src`.
5. Wire it: `RunAssistant(llm=YourAdapter(), registry=default_registry())`.

`AnthropicAdapterSkeleton` and `OpenAIAdapterSkeleton` (`llm_adapters.py`) are
commented reference points — they raise `NotImplementedError`, import no SDK,
read no key, make no call.

## The stub that ships

`RuleBasedAdapter` — deterministic, network-free, regex intent parsing
(model, resource, example, `NNN K`, `N nodes`). Used by demos and the
evaluation harness. It never fabricates a scientific value the user did not
state and cannot emit an approve/execute call.
