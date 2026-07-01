alter table media_tags
    add column normalized_value varchar(255);

update media_tags
   set normalized_value = lower(tag_value);

alter table media_tags
    alter column normalized_value set not null;

create index idx_media_tags_normalized
    on media_tags(normalized_value);

create unique index uq_media_tags_asset_source_normalized
    on media_tags(asset_id, tag_source, normalized_value);
