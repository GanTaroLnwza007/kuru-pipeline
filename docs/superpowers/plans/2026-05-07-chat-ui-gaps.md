# Chat UI Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four gaps in the KUru frontend chat UI so the real backend is fully wired: conversation history sent on every request, response fields (confidence_level / sources / used_tcas_data) correctly typed and rendered, source chips show the right data, and thumbs-up/down feedback is submitted to the backend.

**Architecture:** All changes live in `kuru/frontend/src/`. The schema is the source of truth — fix it first, then the components that depend on it cascade naturally. No new routes or backend changes needed.

**Tech Stack:** Next.js 14 (App Router), TypeScript, Zod, Zustand, Tailwind CSS, Vitest

---

## File map

| File | Change |
|------|--------|
| `src/lib/api/schemas.generated.ts` | Add `ConversationTurn`, `ChatSourceChunk`, update `chatRequestSchema` + `chatDataSchema` |
| `src/lib/api/mock-data.ts` | Change `MOCK_CHAT_SOURCES` to `ChatSourceChunk[]` shape |
| `src/lib/api/mock-client.ts` | Return `confidence_level`, `sources`, `used_tcas_data` in mock `ChatData` |
| `src/lib/api/client.ts` | Add `chatFeedback()` to `realApiClient` |
| `src/lib/api/index.ts` | Add `chatFeedback()` to `apiClient`, export `ChatSourceChunk` |
| `src/lib/store.ts` | Add `confidenceLevel` to `ChatMessage`, change `sources` type |
| `src/components/chat/SourceChip.tsx` | Render `source_file` + similarity %, not table/excerpt |
| `src/components/chat/SourceCitationList.tsx` | Update prop type to `ChatSourceChunk[]` |
| `src/components/chat/FeedbackButtons.tsx` | **Create** — thumbs up/down, submits to `/chat/feedback` |
| `src/components/chat/MessageBubble.tsx` | Add confidence pill, disclaimer for low, `FeedbackButtons` |
| `src/components/chat/MessageList.tsx` | Pass `question` (preceding user message) to each `MessageBubble` |
| `src/app/chat/page.tsx` | Build + send `conversation_history`; store `confidenceLevel` + `sources` |

---

## Task 1: Fix schemas.generated.ts

**Files:**
- Modify: `kuru/frontend/src/lib/api/schemas.generated.ts`

- [ ] **Step 1: Replace the chat section of schemas.generated.ts**

Open `src/lib/api/schemas.generated.ts`. Replace everything from `// ---------- Chat ----------` to the end of the file with:

```ts
// ---------- Chat ----------

export const conversationTurnSchema = z.object({
  role: z.enum(["user", "assistant"]),
  content: z.string(),
});

export const chatRequestSchema = z.object({
  message: z.string().min(1),
  program_context_id: z.string().nullable().optional(),
  session_id: z.string().nullable().optional(),
  conversation_history: z.array(conversationTurnSchema).default([]),
});

export const chatSourceChunkSchema = z.object({
  source_file: z.string(),
  section_type: z.string(),
  similarity: z.number(),
});

export const chatDataSchema = z.object({
  answer: z.string(),
  session_id: z.string(),
  confidence_level: z.enum(["high", "medium", "low"]).default("low"),
  sources: z.array(chatSourceChunkSchema).default([]),
  used_tcas_data: z.boolean().default(false),
});

export const chatResponseSchema = createKuruResponseSchema(chatDataSchema);

// ---------- Inferred types ----------

export type SourceChunk = z.infer<typeof sourceChunkSchema>;
export type PloItem = z.infer<typeof ploItemSchema>;
export type TcasRound = z.infer<typeof tcasRoundSchema>;
export type ProgramSummary = z.infer<typeof programSummarySchema>;
export type ProgramSearchResult = z.infer<typeof programSearchResultSchema>;
export type ProgramDetail = z.infer<typeof programDetailSchema>;
export type ConversationTurn = z.infer<typeof conversationTurnSchema>;
export type ChatSourceChunk = z.infer<typeof chatSourceChunkSchema>;
export type ChatRequest = z.infer<typeof chatRequestSchema>;
export type ChatData = z.infer<typeof chatDataSchema>;
```

- [ ] **Step 2: Type-check**

```powershell
cd kuru\frontend
npx tsc --noEmit 2>&1 | Select-String "schemas.generated"
```

Expected: no errors mentioning `schemas.generated.ts`.

- [ ] **Step 3: Commit**

```powershell
git add src/lib/api/schemas.generated.ts
git commit -m "feat(schema): add ChatSourceChunk, ConversationTurn, confidence_level to chat contract"
```

---

## Task 2: Fix mock data and mock client

**Files:**
- Modify: `kuru/frontend/src/lib/api/mock-data.ts`
- Modify: `kuru/frontend/src/lib/api/mock-client.ts`

- [ ] **Step 1: Update MOCK_CHAT_SOURCES in mock-data.ts**

In `src/lib/api/mock-data.ts`, change the import at line 1 from:

```ts
import type { ProgramDetail, ProgramSummary, SourceChunk } from "./schemas.generated";
```

to:

```ts
import type { ChatSourceChunk, ProgramDetail, ProgramSummary, SourceChunk } from "./schemas.generated";
```

Then replace the `MOCK_CHAT_SOURCES` block (currently lines 220–231) with:

```ts
export const MOCK_CHAT_SOURCES: ChatSourceChunk[] = [
  { source_file: "CPE-69-TCAS3.pdf", section_type: "tcas", similarity: 0.82 },
  { source_file: "SKE-curriculum-2567.pdf", section_type: "overview", similarity: 0.71 },
];
```

- [ ] **Step 2: Update mock-client.ts chat return value**

In `src/lib/api/mock-client.ts`, update the `MockApiClient` type's `chat` method return type — change `sources: typeof MOCK_CHAT_SOURCES` to `sources: never[]`:

```ts
export type MockApiClient = {
  // ... searchPrograms and getProgramDetail unchanged ...
  chat(payload: ChatRequest): Promise<{
    data: ChatData;
    sources: never[];
    isMock: true;
  }>;
};
```

Then update the `chat` implementation's return value. Find the `return { data: { answer, session_id: ... }, sources: MOCK_CHAT_SOURCES, isMock: true }` block and replace with:

```ts
return {
  data: {
    answer,
    session_id: session_id ?? uuid(),
    confidence_level: "high" as const,
    sources: MOCK_CHAT_SOURCES,
    used_tcas_data: false,
  },
  sources: [],
  isMock: true,
};
```

- [ ] **Step 3: Type-check**

```powershell
npx tsc --noEmit 2>&1 | Select-String "mock-data|mock-client"
```

Expected: no errors.

- [ ] **Step 4: Commit**

```powershell
git add src/lib/api/mock-data.ts src/lib/api/mock-client.ts
git commit -m "feat(mock): align mock chat sources and data to real API shape"
```

---

## Task 3: Update store + fix source components

**Files:**
- Modify: `kuru/frontend/src/lib/store.ts`
- Modify: `kuru/frontend/src/components/chat/SourceChip.tsx`
- Modify: `kuru/frontend/src/components/chat/SourceCitationList.tsx`

- [ ] **Step 1: Update ChatMessage type in store.ts**

In `src/lib/store.ts`, change the import at line 2:

```ts
import type { ChatSourceChunk } from "./api/schemas.generated";
```

(Remove `SourceChunk` from that import — it's no longer used in store.)

Replace the `ChatMessage` type:

```ts
export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  confidenceLevel?: "high" | "medium" | "low";
  sources?: ChatSourceChunk[];
  isMock?: boolean;
};
```

- [ ] **Step 2: Rewrite SourceChip.tsx**

Replace the entire contents of `src/components/chat/SourceChip.tsx` with:

```tsx
import type { ChatSourceChunk } from "@/lib/api/schemas.generated";

type Props = {
  source: ChatSourceChunk;
};

export function SourceChip({ source }: Props) {
  const pct = Math.round(source.similarity * 100);
  const name = source.source_file.replace(/\.[^/.]+$/, "");
  const display = name.length > 28 ? name.slice(0, 28) + "…" : name;

  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-paper px-3 py-1 text-xs text-ink-3">
      <svg
        width="11"
        height="11"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        aria-hidden
      >
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
      <span className="font-medium text-ink-2">{display}</span>
      <span className="text-ink-4">{pct}%</span>
    </span>
  );
}
```

- [ ] **Step 3: Update SourceCitationList.tsx**

Replace the entire contents of `src/components/chat/SourceCitationList.tsx` with:

```tsx
import type { ChatSourceChunk } from "@/lib/api/schemas.generated";
import { SourceChip } from "./SourceChip";

type Props = {
  sources: ChatSourceChunk[];
  label: string;
};

export function SourceCitationList({ sources, label }: Props) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="mt-2">
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-4">{label}</p>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {sources.map((source, i) => (
          <SourceChip key={`${source.source_file}-${i}`} source={source} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Type-check**

```powershell
npx tsc --noEmit 2>&1 | Select-String "store|SourceChip|SourceCitation"
```

Expected: no errors.

- [ ] **Step 5: Commit**

```powershell
git add src/lib/store.ts src/components/chat/SourceChip.tsx src/components/chat/SourceCitationList.tsx
git commit -m "feat(chat): align ChatMessage and source chips to ChatSourceChunk shape"
```

---

## Task 4: Wire conversation_history and real sources in page.tsx + client

**Files:**
- Modify: `kuru/frontend/src/lib/api/client.ts`
- Modify: `kuru/frontend/src/lib/api/index.ts`
- Modify: `kuru/frontend/src/app/chat/page.tsx`

- [ ] **Step 1: Add chatFeedback to realApiClient in client.ts**

At the end of the `realApiClient` object in `src/lib/api/client.ts` (after the `chat` method, before the closing `};`), add:

```ts
  async chatFeedback(payload: {
    session_id: string;
    question: string;
    answer: string;
    rating: number;
  }): Promise<void> {
    const base = getApiBaseUrl().replace(/\/$/, "");
    await fetch(`${base}/chat/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
```

Note: uses raw `fetch` because the feedback endpoint returns `{"ok":true}` without the standard `KuruResponseEnvelope` wrapper.

- [ ] **Step 2: Add chatFeedback to apiClient in index.ts**

In `src/lib/api/index.ts`, add `ChatSourceChunk` to the re-export at the bottom:

```ts
export type {
  SourceChunk,
  ChatSourceChunk,   // ← add this
  PloItem,
  TcasRound,
  ProgramSummary,
  ProgramSearchResult,
  ProgramDetail,
  ChatRequest,
  ChatData,
} from "./schemas.generated";
```

Then add `chatFeedback` to the `apiClient` object (after the `chat` method):

```ts
  async chatFeedback(payload: {
    session_id: string;
    question: string;
    answer: string;
    rating: number;
  }): Promise<void> {
    if (useMock) return; // no-op: feedback not tracked in mock mode
    return realApiClient.chatFeedback(payload);
  },
```

- [ ] **Step 3: Update sendMessage in chat/page.tsx**

In `src/app/chat/page.tsx`, find the `sendMessage` callback. Replace the entire callback body with:

```ts
async (text: string) => {
  if (isLoading) return;

  // Capture history before the new user message is added to the store
  const history = messages
    .slice(-10)
    .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

  addMessage({
    id: generateId(),
    role: "user",
    content: text,
    createdAt: new Date().toISOString(),
  });

  setLoading(true);

  try {
    const response = await apiClient.chat({
      message: text,
      program_context_id: programId ?? undefined,
      session_id: sessionId ?? undefined,
      conversation_history: history,
    });

    const data = response.data;
    const isMock = "isMock" in response && response.isMock === true;

    setSessionId(data.session_id);

    addMessage({
      id: generateId(),
      role: "assistant",
      content: data.answer,
      createdAt: new Date().toISOString(),
      confidenceLevel: data.confidence_level,
      sources: data.sources,
      isMock,
    });
  } catch {
    addMessage({
      id: generateId(),
      role: "assistant",
      content: t("errorSend"),
      createdAt: new Date().toISOString(),
    });
  } finally {
    setLoading(false);
  }
},
```

Also update the dependency array to remove the stale `response.sources` cast — the `sources` line is gone so `useCallback` deps are unchanged.

- [ ] **Step 4: Type-check**

```powershell
npx tsc --noEmit 2>&1 | Select-String "page|client|index"
```

Expected: no errors.

- [ ] **Step 5: Commit**

```powershell
git add src/lib/api/client.ts src/lib/api/index.ts src/app/chat/page.tsx
git commit -m "feat(chat): send conversation_history, wire confidence_level and sources from real API"
```

---

## Task 5: Confidence badge + FeedbackButtons

**Files:**
- Create: `kuru/frontend/src/components/chat/FeedbackButtons.tsx`
- Modify: `kuru/frontend/src/components/chat/MessageBubble.tsx`
- Modify: `kuru/frontend/src/components/chat/MessageList.tsx`

- [ ] **Step 1: Create FeedbackButtons.tsx**

Create `src/components/chat/FeedbackButtons.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useAppStore } from "@/lib/store";
import { apiClient } from "@/lib/api";

type Props = {
  question: string;
  answer: string;
};

export function FeedbackButtons({ question, answer }: Props) {
  const sessionId = useAppStore((s) => s.chat.sessionId);
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(value: 1 | -1) {
    if (rating !== null || submitting || !sessionId) return;
    setSubmitting(true);
    try {
      await apiClient.chatFeedback({ session_id: sessionId, question, answer, rating: value });
      setRating(value);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-1 flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => submit(1)}
        disabled={rating !== null || submitting}
        aria-label="มีประโยชน์"
        title="มีประโยชน์"
        className={`grid h-7 w-7 place-items-center rounded-lg border text-sm transition-colors disabled:cursor-default ${
          rating === 1
            ? "border-green-300 bg-green-50 text-green-700"
            : "border-line text-ink-4 hover:border-ink hover:text-ink disabled:opacity-50"
        }`}
      >
        👍
      </button>
      <button
        type="button"
        onClick={() => submit(-1)}
        disabled={rating !== null || submitting}
        aria-label="ไม่มีประโยชน์"
        title="ไม่มีประโยชน์"
        className={`grid h-7 w-7 place-items-center rounded-lg border text-sm transition-colors disabled:cursor-default ${
          rating === -1
            ? "border-red-300 bg-red-50 text-red-600"
            : "border-line text-ink-4 hover:border-ink hover:text-ink disabled:opacity-50"
        }`}
      >
        👎
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite MessageBubble.tsx**

Replace the entire contents of `src/components/chat/MessageBubble.tsx` with:

```tsx
import type { ChatMessage } from "@/lib/store";
import { SourceCitationList } from "./SourceCitationList";
import { FeedbackButtons } from "./FeedbackButtons";

type Props = {
  message: ChatMessage;
  sourcesLabel: string;
  mockBadgeLabel: string;
  question: string;
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return (
    String(d.getHours()).padStart(2, "0") +
    ":" +
    String(d.getMinutes()).padStart(2, "0")
  );
}

function BotAvatar() {
  return (
    <div className="relative grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-[10px] bg-ink">
      <span
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(circle at 30% 30%, var(--d-green-pop), transparent 60%)",
          opacity: 0.7,
        }}
      />
      <span className="relative font-serif text-sm font-semibold italic text-white">K</span>
    </div>
  );
}

function UserAvatar() {
  return (
    <div
      className="grid h-8 w-8 shrink-0 place-items-center rounded-[10px] font-serif text-sm font-semibold italic"
      style={{ background: "var(--d-peach-soft)", color: "var(--d-rust)" }}
    >
      ก
    </div>
  );
}

const CONFIDENCE_STYLES: Record<string, string> = {
  high: "border-green-200 bg-green-50 text-green-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  low: "border-red-200 bg-red-50 text-red-600",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

function ConfidencePill({ level }: { level: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${CONFIDENCE_STYLES[level] ?? ""}`}
    >
      {CONFIDENCE_LABELS[level] ?? level}
    </span>
  );
}

export function MessageBubble({ message, sourcesLabel, mockBadgeLabel, question }: Props) {
  const isUser = message.role === "user";

  return (
    <div
      className={`flex max-w-[92%] gap-3 ${isUser ? "self-end flex-row-reverse" : "self-start"}`}
      style={{ animation: "slideUp 320ms cubic-bezier(.2,.7,.2,1)" }}
    >
      {isUser ? <UserAvatar /> : <BotAvatar />}

      <div className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
        {/* Bubble */}
        <div
          className="px-[18px] py-3.5 text-[15px] leading-[1.55] whitespace-pre-wrap"
          style={
            isUser
              ? { background: "var(--ink)", color: "#fff", borderRadius: "18px 18px 6px 18px" }
              : { background: "var(--paper)", color: "var(--ink)", borderRadius: "18px 18px 18px 6px" }
          }
        >
          {message.content}
        </div>

        {/* Confidence pill — assistant only */}
        {!isUser && message.confidenceLevel && (
          <ConfidencePill level={message.confidenceLevel} />
        )}

        {/* Low-confidence disclaimer */}
        {!isUser && message.confidenceLevel === "low" && (
          <p className="max-w-xs rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-800">
            ข้อมูลนี้อาจไม่ครบถ้วน / This answer may be incomplete.
          </p>
        )}

        {/* Mock badge */}
        {!isUser && message.isMock && (
          <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
            {mockBadgeLabel}
          </span>
        )}

        {/* Source chips */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <SourceCitationList sources={message.sources} label={sourcesLabel} />
        )}

        {/* Feedback buttons — assistant only, after load */}
        {!isUser && (
          <FeedbackButtons question={question} answer={message.content} />
        )}

        {/* Timestamp */}
        <div
          className="px-1 text-[11px] text-ink-4"
          style={isUser ? { textAlign: "right" } : undefined}
        >
          {formatTime(message.createdAt)}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Update MessageList.tsx to pass question**

In `src/components/chat/MessageList.tsx`, find the `messages.map(...)` block inside the `MessageList` component and replace it with:

```tsx
messages.map((message, i) => {
  const question =
    message.role === "assistant"
      ? messages
          .slice(0, i)
          .reverse()
          .find((m) => m.role === "user")?.content ?? ""
      : "";
  return (
    <MessageBubble
      key={message.id}
      message={message}
      sourcesLabel={sourcesLabel}
      mockBadgeLabel={mockBadgeLabel}
      question={question}
    />
  );
})
```

- [ ] **Step 4: Type-check the full project**

```powershell
npx tsc --noEmit
```

Expected: zero errors. If there are errors, fix them before committing.

- [ ] **Step 5: Start dev server and verify visually**

```powershell
# Terminal 1 — backend (if not already running)
cd ..\..\kuru-pipeline
# ensure backend is running on :8000

# Terminal 2 — frontend
cd kuru\frontend
npm run dev
```

Open http://localhost:3000/chat and confirm:
1. Welcome greeting bubble appears immediately
2. Type a question — typing indicator shows, then answer arrives
3. Answer bubble has confidence pill (green High / yellow Medium / red Low)
4. Source chips show filename + similarity %
5. 👍👎 buttons appear below the answer; clicking one highlights it and stays highlighted
6. Low-confidence answer shows the Thai/English disclaimer
7. Open browser devtools Network tab — the `/chat` request body includes `conversation_history` on the second message

- [ ] **Step 6: Commit**

```powershell
git add src/components/chat/FeedbackButtons.tsx src/components/chat/MessageBubble.tsx src/components/chat/MessageList.tsx
git commit -m "feat(chat): confidence badge, low-confidence disclaimer, thumbs feedback"
```

---

## Self-review

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| `conversation_history` in request | Task 1 (schema) + Task 4 (page.tsx) |
| `confidence_level` rendered as badge | Task 1 (schema) + Task 5 (MessageBubble) |
| Low-confidence disclaimer | Task 5 (MessageBubble) |
| `sources` (ChatSourceChunk) typed correctly | Task 1 + Task 3 |
| Source chips show filename + similarity | Task 3 (SourceChip) |
| `POST /chat/feedback` endpoint called | Task 4 (client.ts/index.ts) + Task 5 (FeedbackButtons) |
| Feedback visible after load, not during | FeedbackButtons only renders after message is in store (loading = false) |
| Mock mode returns correct shape | Task 2 (mock-data, mock-client) |

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency check:**
- `ChatSourceChunk` defined in Task 1, used in Tasks 3, 4, 5 ✓
- `ConversationTurn` defined in Task 1, used in Task 4 (`history` map) ✓
- `confidenceLevel` added to `ChatMessage` in Task 3, set in Task 4, read in Task 5 ✓
- `chatFeedback` added to `realApiClient` in Task 4, consumed in `FeedbackButtons` via `apiClient` in Task 5 ✓
