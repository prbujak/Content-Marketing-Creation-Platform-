create table if not exists records (
  kind text not null,
  id text not null,
  owner_id text not null,
  brand_id text,
  payload jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (kind, id)
);

create index if not exists records_owner_kind_updated_idx
  on records (owner_id, kind, updated_at desc);

create index if not exists records_owner_brand_kind_idx
  on records (owner_id, brand_id, kind);
