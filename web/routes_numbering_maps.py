"""Explicit episode-map preview and authenticated, serialized management."""
from flask import g, jsonify
from core import numbering_maps as maps, tmdb_client
from core.cancellation import ProcessingCancelled, check_cancelled
from core.log_redaction import redact
from .auth import require_auth
from .task_state import request_config


def register(app):
    config_path=app.config['CONFIG_PATH']

    def proposal(data, config):
        preview=maps.preview(config, **{key:data.get(key) for key in
                            ('scope','src_path','tmdb_id','kind','season','episode','source_label','start','end')})
        from pathlib import Path
        from core.special_mapping import match_special_mapping
        src=Path(preview['src_path']); identity=preview['tmdb_id']; target=(preview['season'],preview['episode'])
        old=match_special_mapping(src.name,config.get('special_mappings', []))
        if old and (old['tmdb_id'] != identity or old['media_type'] != 'tv'
                    or (old.get('season') is not None and old['season'] != target[0])
                    or (old.get('episode') is not None and old['episode'] != target[1])):
            raise maps.MappingConflict('编号映射与旧人工映射冲突，需要人工确认')
        if config.get('user_rules',{}).get('enabled') is True:
            from core import user_recognition_rules
            from core.parser_regex import parse_with_regex
            try:
                current=user_recognition_rules.match_rule(src,config,{})
                if current is None and '.' in preview['source_label']:
                    title=maps.decimal_title_hint(src.name)
                    if title:
                        current=user_recognition_rules.match_rule(src,config,{'title':title,'media_type':'tv'})
                if current is None and '.' not in preview['source_label']:
                    parsed=parse_with_regex(src.name,src.parent.name)
                    if parsed.get('media_type') == 'tv':
                        current=user_recognition_rules.match_rule(src,config,parsed)
                if current and (current['tmdb_id'] != identity or current['media_type'] != 'tv'
                                or (current['scope']=='file' and (current['season'],current['episode']) != target)):
                    raise maps.MappingConflict('编号映射与人工规则冲突，需要人工确认')
            except user_recognition_rules.RuleValidationError as error:
                raise maps.MappingConflict(str(error)) from error
        if config.get('identity_hints',{}).get('enabled') is True:
            from core.explicit_media_identity import extract_path_identity, extract_nfo_identity, explicit_media_type, IdentityEvidenceError
            try:
                roots=config.get('source_folders',[])
                path_id=extract_path_identity(src,roots);nfo=extract_nfo_identity(src,roots)
                kind=explicit_media_type(src,roots) if path_id is not None or nfo else None
                if (path_id is not None and path_id != identity) or (nfo and nfo != ('tv',identity)) or (kind and kind != 'tv'):
                    raise maps.MappingConflict('编号映射与路径或 NFO 身份冲突，需要人工确认')
            except IdentityEvidenceError as error:
                raise maps.MappingConflict(str(error)) from error
        return preview

    def verify(data, config):
        api=config['tmdb_api'];ident=data['tmdb_id'];season=data['season']
        try:
            details=tmdb_client.get_tmdb_details('tv',ident,api['api_key'],api.get('language','zh-CN'),proxy=api.get('proxy'))
            if not isinstance(details,dict) or type(details.get('id')) is not int or details['id']!=ident or not isinstance(details.get('name'),str) or not details['name'].strip():
                return 'target_unknown'
            seasons=details.get('seasons')
            if not isinstance(seasons,list):return 'target_unknown'
            if not any(isinstance(item,dict) and type(item.get('season_number')) is int and item['season_number']==season for item in seasons):
                return 'target_missing'
            episodes=tmdb_client.get_tv_season_episodes(ident,season,api['api_key'],api.get('language','zh-CN'),proxy=api.get('proxy'))
            if not isinstance(episodes,list) or not episodes:return 'target_unknown'
            numbers=[item.get('episode_number') for item in episodes if isinstance(item,dict)]
            if len(numbers)!=len(episodes) or any(type(n) is not int or n<1 for n in numbers) or len(set(numbers))!=len(numbers):
                return 'target_unknown'
            last=data['episode'] + (data['end']-data['start'] if data['kind']=='range' else 0)
            if not all(n in numbers for n in range(data['episode'],last+1)):return 'target_missing'
            return None
        except ProcessingCancelled:
            raise
        except Exception as error:
            app.logger.warning('编号映射目标验证失败: %s', redact(error))
            return 'target_unknown'

    def verified_proposal(data, config):
        try: preview=proposal(data,config)
        except maps.MappingConflict as error:return None,(jsonify({'status':'error','code':'mapping_conflict','message':str(error)}),409)
        except ValueError as error:return None,(jsonify({'status':'error','code':'invalid_mapping','message':str(error)}),400)
        failure=verify(data,config)
        if failure:
            return None,(jsonify({'status':'error','code':failure,'message':'无法确认 TMDB 目标季集' if failure=='target_unknown' else 'TMDB 中不存在目标季集'}),503 if failure=='target_unknown' else 409)
        return preview,None

    @app.route('/api/numbering_maps',methods=['GET'])
    @require_auth
    def get_numbering_maps():
        return jsonify({'rules':[r for r in maps.list_maps() if not r['deleted']]})

    @app.route('/api/numbering_maps/preview',methods=['POST'])
    @require_auth
    def preview_numbering_map():
        from core.execution_mode import preview_mode
        data=g.validated_body
        with preview_mode(True):
            preview,error=verified_proposal(data,request_config(config_path))
        if error:return error
        return jsonify({'status':'success','preview':preview})

    @app.route('/api/numbering_maps',methods=['POST'])
    @require_auth
    def create_numbering_map():
        config=request_config(config_path);data=g.validated_body
        if config.get('dry_run'):return jsonify({'status':'error','message':'模拟模式下不能保存编号映射'}),409
        preview,error=verified_proposal(data,config)
        if error:return error
        check_cancelled()
        try:
            if data['kind']=='exact':
                rule=maps.add_exact(config,data['scope'],data['tmdb_id'],data['source_label'],data['season'],data['episode'])
            else:
                rule=maps.add_range(config,data['scope'],data['tmdb_id'],data['start'],data['end'],data['season'],data['episode'])
        except maps.MappingConflict as error:return jsonify({'status':'error','message':str(error)}),409
        return jsonify({'status':'success','rule':rule,'preview':preview})

    @app.route('/api/numbering_maps/state',methods=['POST'])
    @require_auth
    def set_numbering_map_state():
        config=request_config(config_path);data=g.validated_body
        if config.get('dry_run'):return jsonify({'status':'error','message':'模拟模式下不能修改编号映射'}),409
        if data['enabled']:
            rule=next((r for r in maps.list_maps() if r['id']==data['id'] and not r['deleted']),None)
            if not rule:return jsonify({'status':'error','message':'编号映射不存在'}),400
            try: maps._scope(rule['scope'],config)
            except ValueError as error:return jsonify({'status':'error','message':str(error)}),400
            failure=verify(rule,config)
            if failure:return jsonify({'status':'error','code':failure,'message':'无法确认 TMDB 目标季集'}),503 if failure=='target_unknown' else 409
        check_cancelled()
        try:maps.set_enabled(data['id'],data['enabled'])
        except maps.MappingConflict as error:return jsonify({'status':'error','message':str(error)}),409
        except ValueError as error:return jsonify({'status':'error','message':str(error)}),400
        return jsonify({'status':'success'})
