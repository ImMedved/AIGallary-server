delete from media_tags
where tag_source = 'METADATA'
  and (
    normalized_value like 'resolution-%'
    or normalized_value like 'orientation-%'
    or normalized_value = 'geo-present'
  );
