-- KUru Pipeline — Supabase Schema
-- Run once against your Supabase project.
-- Requires the pgvector extension (enabled in Supabase dashboard or via the line below).

create extension if not exists vector;

-- ─────────────────────────────────────────
-- Programs registry (canonical source of truth)
-- ─────────────────────────────────────────
create table if not exists programs (
  id           text primary key,          -- e.g. 'ku-cpe', 'ku-cs', derived from filename
  name_th      text,
  name_en      text,
  faculty      text,
  degree_level text default 'bachelor',
  created_at   timestamptz default now()
);

-- ─────────────────────────────────────────
-- Document chunks with embeddings
-- Stores มคอ.2 text chunks + Gemini embeddings for RAG retrieval.
-- ─────────────────────────────────────────
create table if not exists chunks (
  id           uuid primary key default gen_random_uuid(),
  program_id   text not null references programs(id) on delete cascade,
  source_file  text not null,             -- original PDF filename
  section_type text,                      -- 'plo' | 'course' | 'admission' | 'general'
  content      text not null,
  embedding    vector(768),               -- Gemini text-embedding-004 output dimension
  metadata     jsonb default '{}',        -- page numbers, chunk index, extraction method
  created_at   timestamptz default now()
);

-- IVFFlat index for fast approximate nearest-neighbour search.
-- 'lists' should be ~sqrt(row_count); 100 is a safe default for PoC.
create index if not exists chunks_embedding_idx
  on chunks using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create index if not exists chunks_program_id_idx on chunks (program_id);
create index if not exists chunks_section_type_idx on chunks (section_type);

-- ─────────────────────────────────────────
-- TCAS structured records
-- Extracted from TCAS Round PDFs by Gemini.
-- ─────────────────────────────────────────
create table if not exists tcas_records (
  id                     uuid primary key default gen_random_uuid(),
  program_id             text references programs(id) on delete set null,
  program_name_raw       text,            -- raw name as extracted (before resolution)
  faculty                text,
  round                  text,            -- 'round1' | 'round2' | 'round3' | 'round4'
  quota                  integer,
  gpax_min               numeric(4,2),
  exam_criteria          jsonb default '{}',
  -- e.g. {"TGAT": {"weight": 0.3, "min_score": 0}, "TPAT3": {"weight": 0.7}}
  portfolio_requirements jsonb default '{}',
  -- e.g. {"required": ["portfolio_pdf"], "preferred": ["awards"]}
  deadlines              jsonb default '{}',
  -- e.g. {"apply_start": "2025-10-01", "apply_end": "2025-10-10"}
  source_file            text,
  created_at             timestamptz default now()
);

create index if not exists tcas_records_program_id_idx on tcas_records (program_id);
create index if not exists tcas_records_round_idx on tcas_records (round);

-- ─────────────────────────────────────────
-- pgvector similarity search RPC function
-- Called by supabase_client.similarity_search()
-- ─────────────────────────────────────────
create or replace function match_chunks(
  query_embedding  vector(768),
  match_count      int     default 5,
  filter_section   text    default null,
  filter_program   text    default null
)
returns table (
  id           uuid,
  program_id   text,
  source_file  text,
  section_type text,
  content      text,
  metadata     jsonb,
  similarity   float
)
language sql stable as $$
  select
    id,
    program_id,
    source_file,
    section_type,
    content,
    metadata,
    1 - (embedding <=> query_embedding) as similarity
  from chunks
  where
    (filter_section is null or section_type = filter_section)
    and (filter_program is null or program_id = filter_program)
  order by embedding <=> query_embedding
  limit match_count;
$$;
