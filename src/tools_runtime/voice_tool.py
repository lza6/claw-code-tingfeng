"""VoiceTool - 语音输入工具 — 从 Aider voice.py 移植

支持语音录制和转文字，使用 sounddevice + pydub + Whisper API。

用法:
    tool = VoiceTool()
    result = tool.execute(action='record')  # 录制语音
    result = tool.execute(action='transcribe', audio_file='path/to/audio.wav')

依赖:
    pip install sounddevice soundfile pydub
"""
from __future__ import annotations

import logging
import math
import os
import queue
import tempfile
import time
import warnings
from pathlib import Path

from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

warnings.filterwarnings(
    "ignore",
    message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
)
warnings.filterwarnings("ignore", category=SyntaxWarning)


class SoundDeviceError(Exception):
    """音频设备错误"""
    pass


class VoiceTool(BaseTool):
    """语音输入工具 — 支持录制和转文字

    功能:
    - 使用 sounddevice 录制音频
    - 使用 Whisper API 转文字
    - 支持多种音频格式 (wav, mp3, webm)
    - 实时音量可视化

    示例:
        >>> tool = VoiceTool()
        >>> # 录制语音
        >>> result = tool.execute(action='record', max_duration=30)
        >>> # 转文字
        >>> result = tool.execute(action='transcribe', audio_file='audio.wav')
    """

    name = 'VoiceTool'
    description = '录制语音并转换为文字，支持多种音频格式'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='action',
            param_type='str',
            required=True,
            description='操作类型: record (录制), transcribe (转文字)',
            allowed_values=('record', 'transcribe'),
        ),
        ParameterSchema(
            name='audio_file',
            param_type='str',
            required=False,
            description='音频文件路径（transcribe 操作必需）',
        ),
        ParameterSchema(
            name='max_duration',
            param_type='int',
            required=False,
            description='最大录制时长（秒，默认 60）',
            default=60,
            min_value=5,
            max_value=300,
        ),
        ParameterSchema(
            name='format',
            param_type='str',
            required=False,
            description='音频格式: wav, mp3, webm（默认 wav）',
            default='wav',
            allowed_values=('wav', 'mp3', 'webm'),
        ),
        ParameterSchema(
            name='language',
            param_type='str',
            required=False,
            description='语音语言（如 zh, en）',
            default=None,
        ),
        ParameterSchema(
            name='device_name',
            param_type='str',
            required=False,
            description='音频输入设备名称',
            default=None,
        ),
    )

    # 音量阈值
    threshold = 0.15
    max_rms = 0
    min_rms = 1e5
    pct = 0

    def __init__(self) -> None:
        """初始化语音工具"""
        self._sd = None
        self._sf = None
        self._device_id = None
        self._q: queue.Queue | None = None
        self._start_time = 0

        # 尝试加载依赖
        self._load_dependencies()

    def _load_dependencies(self) -> None:
        """加载音频依赖"""
        try:
            import soundfile as sf
            self._sf = sf
        except (OSError, ModuleNotFoundError):
            logger.warning('soundfile 未安装，语音功能不可用')
            self._sf = None

        try:
            import sounddevice as sd
            self._sd = sd
        except (OSError, ModuleNotFoundError):
            logger.warning('sounddevice 未安装，语音功能不可用')
            self._sd = None

    def _init_device(self, device_name: str | None = None) -> None:
        """初始化音频设备"""
        if self._sd is None:
            raise SoundDeviceError('sounddevice 未安装')

        devices = self._sd.query_devices()

        if device_name:
            device_id = None
            for i, device in enumerate(devices):
                if device_name in device['name']:
                    device_id = i
                    break
            if device_id is None:
                available_inputs = [d['name'] for d in devices if d['max_input_channels'] > 0]
                raise ValueError(
                    f"设备 '{device_name}' 未找到。可用输入设备: {available_inputs}"
                )
            self._device_id = device_id
        else:
            self._device_id = None

    def validate(self, **kwargs) -> tuple[bool, str]:
        """验证参数"""
        action = kwargs.get('action')
        if not action:
            return False, '缺少 action 参数'

        if action == 'transcribe':
            audio_file = kwargs.get('audio_file')
            if not audio_file:
                return False, 'transcribe 操作需要 audio_file 参数'
            if not Path(audio_file).exists():
                return False, f'音频文件不存在: {audio_file}'

        if action == 'record':
            if self._sf is None:
                return False, 'soundfile 未安装，无法录制'
            if self._sd is None:
                return False, 'sounddevice 未安装，无法录制'

        return True, ''

    def execute(self, **kwargs) -> ToolResult:
        """执行语音操作"""
        action = kwargs.get('action', 'record')

        if action == 'record':
            return self._record(**kwargs)
        elif action == 'transcribe':
            return self._transcribe(**kwargs)
        else:
            return ToolResult(
                success=False,
                output='',
                error=f'未知操作: {action}',
                exit_code=1,
            )

    def _record(self, **kwargs) -> ToolResult:
        """录制音频"""
        device_name = kwargs.get('device_name')
        format = kwargs.get('format', 'wav')
        kwargs.get('language')

        try:
            self._init_device(device_name)
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=str(e),
                exit_code=1,
            )

        if format not in ('wav', 'mp3', 'webm'):
            return ToolResult(
                success=False,
                output='',
                error=f'不支持音频格式: {format}',
                exit_code=1,
            )

        self._q = queue.Queue()
        temp_wav = tempfile.mktemp(suffix='.wav')

        # 获取采样率
        try:
            sample_rate = int(self._sd.query_devices(self._device_id, 'input')['default_samplerate'])
        except (TypeError, ValueError):
            sample_rate = 16000
        except self._sd.PortAudioError:
            return ToolResult(
                success=False,
                output='',
                error='无法获取音频输入设备信息',
                exit_code=1,
            )

        self._start_time = time.time()
        self.max_rms = 0
        self.min_rms = 1e5

        # 录制音频
        try:
            with self._sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                callback=self._callback,
                device=self._device_id,
            ):
                # 简单录制，等待用户输入停止
                # 实际应用中需要更复杂的交互逻辑
                logger.info('正在录制...')
                time.sleep(kwargs.get('max_duration', 60))
        except self._sd.PortAudioError as err:
            return ToolResult(
                success=False,
                output='',
                error=f'音频输入设备错误: {err}',
                exit_code=1,
            )

        # 保存音频
        with self._sf.SoundFile(temp_wav, mode='x', samplerate=sample_rate, channels=1) as file:
            while not self._q.empty():
                file.write(self._q.get())

        # 检查文件大小
        file_size = os.path.getsize(temp_wav)
        use_format = format

        if file_size > 24.9 * 1024 * 1024 and format == 'wav':
            logger.warning('音频文件过大，切换到 mp3 格式')
            use_format = 'mp3'

        filename = temp_wav
        if use_format != 'wav':
            try:
                from pydub import AudioSegment
                new_filename = tempfile.mktemp(suffix=f'.{use_format}')
                audio = AudioSegment.from_wav(temp_wav)
                audio.export(new_filename, format=use_format)
                os.remove(temp_wav)
                filename = new_filename
            except Exception as e:
                logger.warning(f'音频转换失败: {e}')

        duration = time.time() - self._start_time

        return ToolResult(
            success=True,
            output=f'录制完成: {filename} ({duration:.1f}秒)',
            exit_code=0,
        )

    def _callback(self, indata, frames, time_info, status) -> None:
        """音频回调函数"""
        import numpy as np

        rms = np.sqrt(np.mean(indata**2))
        self.max_rms = max(self.max_rms, rms)
        self.min_rms = min(self.min_rms, rms)

        rng = self.max_rms - self.min_rms
        if rng > 0.001:
            self.pct = (rms - self.min_rms) / rng
        else:
            self.pct = 0.5

        if self._q:
            self._q.put(indata.copy())

    def _transcribe(self, **kwargs) -> ToolResult:
        """将音频转为文字"""
        audio_file = kwargs.get('audio_file')
        language = kwargs.get('language')

        if not audio_file:
            return ToolResult(
                success=False,
                output='',
                error='缺少 audio_file 参数',
                exit_code=1,
            )

        path = Path(audio_file)
        if not path.exists():
            return ToolResult(
                success=False,
                output='',
                error=f'音频文件不存在: {audio_file}',
                exit_code=1,
            )

        # 使用 LiteLLM Whisper API
        try:
            from ..llm import get_client

            client = get_client(provider='openai')
            if client is None:
                return ToolResult(
                    success=False,
                    output='',
                    error='无法获取 LLM client',
                    exit_code=1,
                )

            with open(path, 'rb') as fh:
                # 构建转录请求
                # 这里假设使用 OpenAI Whisper API
                response = client.audio.transcriptions.create(
                    model='whisper-1',
                    file=fh,
                    language=language,
                )

                text = response.text

                return ToolResult(
                    success=True,
                    output=text,
                    exit_code=0,
                )

        except ImportError:
            # 回退到直接使用 litellm
            try:
                from litellm import transcription

                with open(path, 'rb') as fh:
                    transcript = transcription(
                        model='whisper-1',
                        file=fh,
                        language=language,
                    )

                return ToolResult(
                    success=True,
                    output=transcript.text,
                    exit_code=0,
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    output='',
                    error=f'转录失败: {e}',
                    exit_code=1,
                )

        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'转录失败: {e}',
                exit_code=1,
            )

    def get_volume_bar(self) -> str:
        """获取音量可视化条"""
        num = 10
        if math.isnan(self.pct) or self.pct < self.threshold:
            cnt = 0
        else:
            cnt = int(self.pct * 10)

        bar = '░' * cnt + '█' * (num - cnt)
        bar = bar[:num]

        dur = time.time() - self._start_time
        return f'录制中... {dur:.1f}秒 {bar}'


def get_available_devices() -> list[dict]:
    """获取可用音频输入设备列表

    返回:
        设备信息列表，每个元素包含 name, max_input_channels 等
    """
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return [
            {'name': d['name'], 'channels': d['max_input_channels']}
            for d in devices
            if d['max_input_channels'] > 0
        ]
    except Exception:
        return []
