"""Explicit, source-scoped and reviewable manual title aliases."""
import hashlib
import json
from pathlib import Path
import re

from flask import g, jsonify
from core import recognition_aliases as aliases, tmdb_client
from core.cancellation import ProcessingCancelled, check_cancelled
from core.execution_mode import preview_mode
from core.log_redaction import redact
from .auth import require_auth
from .task_state import request_config


def _scope(value,config,*,require_dir=True):
    if not isinstance(value,str) or not value or not Path(value).is_absolute():
        raise ValueError('作用域必须是绝对目录')
    path=Path(value)
    if path.resolve()!=path or (require_dir and not path.is_dir()):
        raise ValueError('作用域不存在或包含符号链接/非规范路径')
    roots=[Path(root).resolve() for root in config.get('source_folders',[]) if isinstance(root,str) and root.strip()]
    if not any(path==root or root in path.parents for root in roots):
        raise ValueError('作用域不在配置的源目录内')
    return str(path)


def register(app):
    config_path=app.config['CONFIG_PATH']

    def proposal(data,config):
        scope=_scope(data['scope'],config);kind=data['media_type'];ident=data['tmdb_id']
        # Validate the requested record before the remote lookup.
        aliases._validated({'scope':scope,'media_type':kind,'tmdb_id':ident,'name':data['name'],
                            'source':'manual','year':None})
        api=config['tmdb_api']
        try:
            details=tmdb_client.get_tmdb_details(kind,ident,api['api_key'],api.get('language','zh-CN'),
                                                  include_alternative_titles=True,proxy=api.get('proxy'))
        except ProcessingCancelled:raise
        except Exception as error:
            app.logger.warning('验证别名作品失败: %s',redact(error))
            return None,'identity_unknown'
        title_key='name' if kind=='tv' else 'title';date_key='first_air_date' if kind=='tv' else 'release_date'
        if (not isinstance(details,dict) or type(details.get('id')) is not int or details['id']!=ident
                or not isinstance(details.get(title_key),str) or not details[title_key].strip()):
            return None,'identity_unknown'
        title=details[title_key].strip();date=details.get(date_key)
        year=date[:4] if isinstance(date,str) and re.fullmatch(r'(?:18|19|20|21)\d{2}',date[:4]) else None
        entries=[{'name':data['name'].strip(),'media_type':kind,'tmdb_id':ident,'source':'manual','year':year,'scope':scope}]
        seen={aliases.normalize(entries[0]['name'])}
        for name in (title,details.get('original_name' if kind=='tv' else 'original_title')):
            if isinstance(name,str) and name.strip() and aliases.normalize(name) not in seen:
                entry={'name':name.strip(),'media_type':kind,'tmdb_id':ident,'source':'tmdb','year':year,'scope':scope}
                entries.append(aliases._validated(entry));seen.add(aliases.normalize(name))
        def overlapping(other):
            if other is None:return True
            first,second=Path(scope),Path(other)
            return first==second or first in second.parents or second in first.parents
        others=sorted({r['tmdb_id'] for r in aliases.stored_aliases()
                       if r['source'] in aliases.TRUSTED_SOURCES and r['media_type']==kind and r['tmdb_id']!=ident
                       and aliases.normalize(r['name'])==aliases.normalize(data['name']) and overlapping(r['scope'])})
        preview={'scope':scope,'name':entries[0]['name'],'media_type':kind,'tmdb_id':ident,
                 'title':title,'year':year,'additional_names':[entry['name'] for entry in entries[1:]],
                 'conflicting_ids':others}
        token=hashlib.sha256(json.dumps([preview,entries],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return {'preview':preview,'preview_token':token,'records':entries},None

    def preflight(data,config):
        try:result,error=proposal(data,config)
        except ValueError as error:return None,(jsonify({'status':'error','code':'invalid_alias','message':str(error)}),400)
        if error:return None,(jsonify({'status':'error','code':error,'message':'无法确认 TMDB 作品身份'}),503)
        return result,None

    @app.route('/api/recognition_aliases',methods=['GET'])
    @require_auth
    def get_recognition_aliases():
        return jsonify({'aliases':aliases.manual_aliases()})

    @app.route('/api/recognition_aliases/preview',methods=['POST'])
    @require_auth
    def preview_recognition_alias():
        with preview_mode(True):
            result,error=preflight(g.validated_body,request_config(config_path))
        if error:return error
        return jsonify({'status':'success','preview':result['preview'],'preview_token':result['preview_token']})

    @app.route('/api/recognition_aliases',methods=['POST'])
    @require_auth
    def create_recognition_alias():
        config=request_config(config_path);data=g.validated_body
        if config.get('dry_run'):return jsonify({'status':'error','message':'模拟模式下不能保存别名'}),409
        result,error=preflight(data,config)
        if error:return error
        if data['preview_token']!=result['preview_token']:
            return jsonify({'status':'error','code':'preview_changed','message':'预览内容或作品详情已变化，请重新预览'}),409
        check_cancelled();_scope(data['scope'],config)
        aliases.add_aliases(result['records'])
        return jsonify({'status':'success','preview':result['preview'],
                        'active':config.get('recognition_aliases',{}).get('enabled') is True})

    @app.route('/api/recognition_aliases/delete',methods=['POST'])
    @require_auth
    def delete_recognition_alias():
        config=request_config(config_path);record=g.validated_body['record']
        if config.get('dry_run'):return jsonify({'status':'error','message':'模拟模式下不能删除别名'}),409
        try:
            _scope(record['scope'],config,require_dir=False)
            check_cancelled();aliases.remove_manual_alias(record)
        except ValueError as error:return jsonify({'status':'error','message':str(error)}),400
        return jsonify({'status':'success'})
