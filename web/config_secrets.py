"""Secret values are write-only in the configuration API."""

from copy import deepcopy

SECRET_FIELDS = {"auth.password", "tmdb_api.api_key", "ai_parser.api_key", "ai_plot_enhance.api_key"}


def configured(value):
    return bool(value) and value not in {"YOUR_API_KEY", "YOUR_TMDB_API_KEY_V3"}


def public_config(config):
    def scrub(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in {"api_key", "password"}:
                    result[key] = ""
                    result[key + "_configured"] = configured(item)
                else:
                    result[key] = scrub(item)
            return result
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value
    return scrub(config)


def merge_config(existing, payload):
    if not isinstance(payload, dict):
        raise ValueError("配置必须为对象")
    patch = deepcopy(payload)
    clear = patch.pop("clear_secrets", [])
    if not isinstance(clear, list) or any(not isinstance(key, str) or key not in SECRET_FIELDS for key in clear):
        raise ValueError("无效的密钥清除字段")
    result = deepcopy(existing)
    for section, value in patch.items():
        if section.endswith("_configured"):
            continue
        if section in {key.split(".")[0] for key in SECRET_FIELDS} and not isinstance(value, dict):
            raise ValueError("密钥配置必须为对象")
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if not key.endswith("_configured")}
            for field in ("api_key", "password"):
                if field in value:
                    if not isinstance(value[field], str):
                        raise ValueError("密钥必须为字符串")
                    if not value[field]:
                        del value[field]
            result[section] = {**result.get(section, {}), **value}
        else:
            result[section] = value
    for key in clear:
        section, field = key.split(".")
        if patch.get(section, {}).get(field):
            raise ValueError("不能同时设置与清除同一密钥")
        result.setdefault(section, {})[field] = ""
        if section in ("ai_parser", "ai_plot_enhance"):
            result[section]["enabled"] = False
    auth = result.get("auth", {})
    if type(auth.get("enabled", False)) is not bool:
        raise ValueError("认证开关必须为布尔值")
    if auth.get("enabled") and any(not isinstance(auth.get(key), str) or not auth[key]
                                   for key in ("username", "password")):
        raise ValueError("启用认证需要非空用户名和密码")
    return result
