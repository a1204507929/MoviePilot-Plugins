import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import EventType
from app.utils.http import RequestUtils

lock = threading.Lock()
scheduler_lock = threading.Lock()

# API地址
SIXTY_SECONDS_API = "https://60s-api.viki.moe/v2/60s"

class SixtySecondsWorld(_PluginBase):
    # 插件元数据
    plugin_name = "60秒读懂世界"
    plugin_desc = "每日推送全球要闻速览，并在仪表盘中显示最新简报。"
    plugin_icon = "https://raw.githubusercontent.com/InfinityPacer/MoviePilot-Plugins/main/icons/news.png"
    plugin_version = "1.0"
    plugin_author = "MoviePilot"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "sixtyseconds_"
    plugin_order = 81
    auth_level = 1

    # 私有属性
    _enabled = False
    _cron = "0 8 * * *"
    _notify = False
    _onlyonce = False
    _cover = True
    _last_update = None
    _scheduler = None
    _data = {}

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled", False)
            self._cron = config.get("cron", "0 8 * * *")
            self._notify = config.get("notify", False)
            self._onlyonce = config.get("onlyonce", False)
            self._cover = config.get("cover", True)

        # 立即运行一次
        if self._onlyonce:
            self._onlyonce = False
            self.update_config({
                "enabled": self._enabled,
                "cron": self._cron,
                "notify": self._notify,
                "onlyonce": False,
                "cover": self._cover
            })
            self.__fetch_data()

        # 启动定时任务
        if self._enabled:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            
            # 添加定时任务
            if self._cron:
                try:
                    self._scheduler.add_job(
                        func=self.__fetch_data,
                        trigger=CronTrigger.from_crontab(self._cron),
                        name="60秒读懂世界"
                    )
                except Exception as e:
                    logger.error(f"定时任务配置错误: {str(e)}")
                    self.systemmessage.put(f"定时任务配置错误: {str(e)}")
            
            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/60s",
                "event": EventType.PluginAction,
                "desc": "60秒读懂世界",
                "category": "资讯",
                "data": {"action": "sixty_seconds"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/sixty_seconds",
                "endpoint": self.get_data,
                "methods": ["GET"],
                "summary": "获取60秒读懂世界数据",
                "description": "返回最新的60秒读懂世界数据"
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        },
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        },
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'cover',
                                            'label': '显示封面图片',
                                        },
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        },
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式',
                                        },
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '数据来源于60秒读懂世界API，每日自动更新全球要闻速览'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "cron": "0 8 * * *",
            "notify": True,
            "onlyonce": False,
            "cover": True
        }

    def get_page(self) -> List[dict]:
        # 详细页面实现
        if not self._data:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                        'style': 'margin-top: 50px'
                    }
                }
            ]
        
        return [
            {
                'component': 'VCard',
                'content': [
                    {
                        'component': 'div',
                        'props': {
                            'class': 'pa-4'
                        },
                        'content': [
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'text-h5 mb-2'
                                },
                                'text': f"60秒读懂世界 · {self._data.get('date', '')}"
                            },
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'text-caption mb-3'
                                },
                                'text': self._data.get('tip', '')
                            },
                            {
                                'component': 'VImg',
                                'props': {
                                    'src': self._data.get('cover', ''),
                                    'max-width': '100%',
                                    'class': 'mb-4'
                                }
                            } if self._cover else None,
                            {
                                'component': 'div',
                                'content': [
                                    {
                                        'component': 'div',
                                        'props': {
                                            'class': 'mb-2'
                                        },
                                        'text': f"{idx+1}. {item}"
                                    } for idx, item in enumerate(self._data.get('news', []))
                                ]
                            },
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'mt-4'
                                },
                                'content': [
                                    {
                                        'component': 'a',
                                        'props': {
                                            'href': self._data.get('link', ''),
                                            'target': '_blank',
                                            'class': 'text-decoration-none'
                                        },
                                        'text': '查看详情'
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def get_dashboard(self, **kwargs) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], List[dict]]:
        """
        获取仪表盘组件
        """
        if not self._data:
            return None
            
        # 仪表板配置
        dashboard_cols = {
            "cols": 12,
            "md": 6
        }
        
        # 全局配置
        dashboard_attrs = {
            "border": False
        }
        
        # 组件内容
        dashboard_content = [
            {
                'component': 'VCard',
                'props': {
                    'class': 'h-100'
                },
                'content': [
                    {
                        'component': 'VCardItem',
                        'content': [
                            {
                                'component': 'VCardTitle',
                                'props': {
                                    'class': 'pa-2'
                                },
                                'text': f"60秒读懂世界 · {self._data.get('date', '')}"
                            },
                            {
                                'component': 'VCardSubtitle',
                                'props': {
                                    'class': 'pa-2'
                                },
                                'text': self._data.get('tip', '')
                            }
                        ]
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-2'
                        },
                        'content': [
                            {
                                'component': 'VImg',
                                'props': {
                                    'src': self._data.get('cover', ''),
                                    'max-width': '100%',
                                    'height': 'auto'
                                }
                            } if self._cover else None
                        ]
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-2'
                        },
                        'content': [
                            {
                                'component': 'div',
                                'props': {
                                    'class': 'mb-1 text-truncate'
                                },
                                'text': f"{idx+1}. {item}"
                            } for idx, item in enumerate(self._data.get('news', [])[:3]
                        ]
                    },
                    {
                        'component': 'VCardActions',
                        'props': {
                            'class': 'pa-2'
                        },
                        'content': [
                            {
                                'component': 'VBtn',
                                'props': {
                                    'variant': 'text',
                                    'color': 'primary',
                                    'href': self._data.get('link', ''),
                                    'target': '_blank'
                                },
                                'text': '查看详情'
                            }
                        ]
                    }
                ]
            }
        ]
        
        return dashboard_cols, dashboard_attrs, dashboard_content

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        if not self._enabled:
            return []
            
        return [{
            "id": "SixtySeconds",
            "name": "60秒读懂世界定时服务",
            "trigger": CronTrigger.from_crontab(self._cron),
            "func": self.__fetch_data,
            "kwargs": {}
        }]

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error(f"停止服务失败: {str(e)}")

    def __fetch_data(self):
        """
        获取数据
        """
        try:
            logger.info("开始获取60秒读懂世界数据...")
            res = RequestUtils(timeout=10).get_res(SIXTY_SECONDS_API)
            if res and res.status_code == 200:
                data = res.json()
                if data.get("code") == 200:
                    self._data = data.get("data", {})
                    self._last_update = datetime.now()
                    
                    # 发送通知
                    if self._notify:
                        self.__send_notify()
                        
                    logger.info("60秒读懂世界数据获取成功")
                    return True
                    
            logger.error(f"获取60秒读懂世界数据失败: {res.text if res else '无响应'}")
        except Exception as e:
            logger.error(f"获取60秒读懂世界数据异常: {str(e)}")
        return False

    def __send_notify(self):
        """
        发送通知
        """
        if not self._data:
            return
            
        # 组装消息
        message = f"【60秒读懂世界 · {self._data.get('date', '')}】\n"
        message += f"{self._data.get('tip', '')}\n\n"
        
        for idx, news in enumerate(self._data.get("news", [])[:5]):
            message += f"{idx+1}. {news}\n"
            
        message += f"\n查看详情: {self._data.get('link', '')}"
        
        # 发送通知
        self.post_message(
            mtype=NotificationType.SiteMessage,
            title="60秒读懂世界",
            text=message
        )

    @eventmanager.register(EventType.PluginAction)
    def handle_action(self, event: Event):
        """
        处理事件
        """
        if not event:
            return
            
        event_data = event.event_data
        if not event_data or event_data.get("action") != "sixty_seconds":
            return
            
        logger.info("收到命令，获取60秒读懂世界数据...")
        self.__fetch_data()
        
        # 发送消息
        if self._notify:
            self.__send_notify()
