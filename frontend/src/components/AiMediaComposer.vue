<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Camera,
  Delete,
  Microphone,
  Picture,
  RefreshRight,
  VideoPause,
} from '@element-plus/icons-vue'
import {
  aiMediaApi,
  type AiMediaAsset,
  type AiMediaCapabilities,
} from '@/api/aiMedia'
import { getErrorMessage } from '@/utils/error'

type ImageUploadStatus = 'queued' | 'uploading' | 'ready' | 'failed'
type TranscriptionStatus = 'transcribing' | 'failed'

interface LocalImageEntry {
  key: string
  file: File
  previewUrl: string
  assetId: number | null
  status: ImageUploadStatus
  progress: number
  error: string
  controller: AbortController | null
  removed: boolean
}

interface AudioUploadTask {
  filename: string
  status: 'uploading' | 'failed'
  progress: number
  error: string
}

interface TranscriptionState {
  status: TranscriptionStatus
  error: string
}

const HARD_MAX_IMAGES = 2
const HARD_MAX_AUDIO_SECONDS = 60
const HARD_MAX_IMAGE_EDGE = 2048
const LOSSY_IMAGE_QUALITY = 0.85
const IMAGE_MIME_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

const props = withDefaults(defineProps<{
  courseId?: number | null
  chapterId?: number | null
  disabled?: boolean
}>(), {
  courseId: null,
  chapterId: null,
  disabled: false,
})

const assets = defineModel<AiMediaAsset[]>({ default: () => [] })
const emit = defineEmits<{
  (event: 'transcribed', text: string): void
  (event: 'busy-changed', busy: boolean): void
}>()

const capabilities = ref<AiMediaCapabilities | null>(null)
const capabilityLoading = ref(true)
const capabilityError = ref('')
const localImages = ref<LocalImageEntry[]>([])
const deletingAssetIds = ref<Set<number>>(new Set())
const audioUploadTask = ref<AudioUploadTask | null>(null)
const transcriptionStates = ref<Record<number, TranscriptionState>>({})
const imageInput = ref<HTMLInputElement | null>(null)
const cameraInput = ref<HTMLInputElement | null>(null)
const imagePreparing = ref(false)
const recording = ref(false)
const recordingElapsedMs = ref(0)

let imageSequence = 0
let recorder: MediaRecorder | null = null
let mediaStream: MediaStream | null = null
let recordingTimer: ReturnType<typeof setInterval> | null = null
let recordingStartedAt = 0
let audioUploadController: AbortController | null = null
let disposed = false
const transcriptionControllers = new Map<number, AbortController>()

const imageLimit = computed(() => Math.min(
  HARD_MAX_IMAGES,
  Math.max(0, Math.floor(capabilities.value?.max_images ?? HARD_MAX_IMAGES)),
))
const maxImageBytes = computed(() => Math.max(0, capabilities.value?.max_image_mb ?? 0) * 1024 * 1024)
const maxAudioBytes = computed(() => Math.max(0, capabilities.value?.max_audio_mb ?? 0) * 1024 * 1024)
const maxAudioSeconds = computed(() => Math.min(
  HARD_MAX_AUDIO_SECONDS,
  Math.max(1, Math.floor(capabilities.value?.max_audio_seconds ?? HARD_MAX_AUDIO_SECONDS)),
))
const imageAssets = computed(() => assets.value.filter((asset) => asset.media_kind === 'image'))
const audioAssets = computed(() => assets.value.filter((asset) => asset.media_kind === 'audio'))
const localAssetIds = computed(() => new Set(
  localImages.value.flatMap((entry) => entry.assetId == null ? [] : [entry.assetId]),
))
const imagesWithoutLocalPreview = computed(() => imageAssets.value.filter(
  (asset) => !localAssetIds.value.has(asset.id),
))
const selectedImageCount = computed(() => {
  const pendingCount = localImages.value.filter((entry) => entry.assetId == null && !entry.removed).length
  return imageAssets.value.length + pendingCount
})
const remainingImageSlots = computed(() => Math.max(0, imageLimit.value - selectedImageCount.value))
const browserCanRecord = computed(() => typeof navigator !== 'undefined'
  && Boolean(navigator.mediaDevices?.getUserMedia)
  && typeof MediaRecorder !== 'undefined')
const transcriptionBusy = computed(() => Object.values(transcriptionStates.value)
  .some((state) => state.status === 'transcribing'))
const audioBusy = computed(() => recording.value
  || audioUploadTask.value?.status === 'uploading'
  || transcriptionBusy.value)
const imageTransferBusy = computed(() => imagePreparing.value || localImages.value.some(
  (entry) => entry.status === 'queued' || entry.status === 'uploading',
))

watch(
  () => imageTransferBusy.value || audioBusy.value,
  (busy) => emit('busy-changed', busy),
  { immediate: true },
)

const imageActionDisabled = computed(() => props.disabled
  || capabilityLoading.value
  || !capabilities.value?.image_enabled
  || imageTransferBusy.value
  || remainingImageSlots.value === 0)
const audioActionDisabled = computed(() => props.disabled
  || capabilityLoading.value
  || !capabilities.value?.audio_enabled
  || !browserCanRecord.value
  || audioBusy.value)
const imageActionHint = computed(() => {
  if (capabilityLoading.value) return '正在检测图片能力'
  if (props.disabled) return '当前暂不能添加附件'
  if (!capabilities.value?.image_enabled) return '服务器尚未启用图片理解能力'
  if (imageTransferBusy.value) return imagePreparing.value ? '正在压缩图片' : '正在上传图片'
  if (remainingImageSlots.value === 0) return `每次最多添加 ${imageLimit.value} 张图片`
  return `支持 JPEG、PNG、WebP；最多 ${imageLimit.value} 张，单张不超过 ${formatLimit(capabilities.value.max_image_mb)} MB`
})
const audioActionHint = computed(() => {
  if (capabilityLoading.value) return '正在检测语音能力'
  if (props.disabled) return '当前暂不能录音'
  if (!capabilities.value?.audio_enabled) return '服务器尚未启用语音转写能力'
  if (!browserCanRecord.value) return '当前浏览器不支持录音，请更换新版浏览器'
  if (audioBusy.value) return recording.value ? '正在录音' : '正在处理上一段录音'
  return `最长 ${maxAudioSeconds.value} 秒，不超过 ${formatLimit(capabilities.value.max_audio_mb)} MB`
})
const capabilityHint = computed(() => {
  if (capabilityLoading.value) return '正在检测图片和语音能力…'
  if (capabilityError.value) return capabilityError.value
  if (imagePreparing.value) return `正在优化图片，长边将压缩至 ${HARD_MAX_IMAGE_EDGE}px 以内…`
  const imageEnabled = capabilities.value?.image_enabled
  const audioEnabled = capabilities.value?.audio_enabled
  if (!imageEnabled && !audioEnabled) return '当前服务器未启用图片或语音能力。'
  if (!imageEnabled) return '图片能力未启用，当前仅可使用语音输入。'
  if (!audioEnabled) return '语音能力未启用，当前仅可添加图片。'
  if (!browserCanRecord.value) return '图片功能可用；当前浏览器不支持录音。'
  return `临时媒体最长保留 ${capabilities.value?.retention_hours ?? 24} 小时，个人总额 ${capabilities.value?.user_quota_mb ?? 50} MB。`
})
const recordingTime = computed(() => formatDuration(recordingElapsedMs.value / 1000))

function formatLimit(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(seconds: number | null | undefined) {
  const total = Math.max(0, Math.ceil(seconds || 0))
  const minutes = Math.floor(total / 60)
  return `${String(minutes).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

function isCanceled(error: unknown) {
  return Boolean(error && typeof error === 'object' && 'code' in error
    && (error as { code?: string }).code === 'ERR_CANCELED')
}

function setDeleting(assetId: number, deleting: boolean) {
  const next = new Set(deletingAssetIds.value)
  if (deleting) next.add(assetId)
  else next.delete(assetId)
  deletingAssetIds.value = next
}

function setTranscriptionState(assetId: number, state: TranscriptionState | null) {
  const next = { ...transcriptionStates.value }
  if (state) next[assetId] = state
  else delete next[assetId]
  transcriptionStates.value = next
}

function addAsset(asset: AiMediaAsset) {
  assets.value = [...assets.value.filter((item) => item.id !== asset.id), asset]
}

function removeAssetFromModel(assetId: number) {
  assets.value = assets.value.filter((asset) => asset.id !== assetId)
}

function releaseImageEntry(entry: LocalImageEntry) {
  if (entry.removed) return
  entry.removed = true
  entry.controller?.abort()
  entry.controller = null
  URL.revokeObjectURL(entry.previewUrl)
  localImages.value = localImages.value.filter((item) => item.key !== entry.key)
}

async function loadCapabilities() {
  capabilityLoading.value = true
  capabilityError.value = ''
  try {
    const response = await aiMediaApi.capabilities()
    capabilities.value = response.data.data
  } catch (error) {
    capabilities.value = null
    capabilityError.value = getErrorMessage(error, '无法读取媒体能力，图片和语音已暂时禁用。')
  } finally {
    capabilityLoading.value = false
  }
}

function openImagePicker() {
  if (!imageActionDisabled.value) imageInput.value?.click()
}

function openCamera() {
  if (!imageActionDisabled.value) cameraInput.value?.click()
}

function validateImageType(file: File) {
  if (!IMAGE_MIME_TYPES.has(file.type.toLowerCase())) return '仅支持 JPEG、PNG 或 WebP 图片'
  return ''
}

function validatePreparedImage(file: File) {
  if (maxImageBytes.value <= 0 || file.size > maxImageBytes.value) {
    return `单张图片不能超过 ${formatLimit(capabilities.value?.max_image_mb ?? 0)} MB`
  }
  return ''
}

interface DecodedImage {
  source: CanvasImageSource
  width: number
  height: number
  release: () => void
}

async function decodeImage(file: File): Promise<DecodedImage> {
  if (typeof createImageBitmap === 'function') {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
      return {
        source: bitmap,
        width: bitmap.width,
        height: bitmap.height,
        release: () => bitmap.close(),
      }
    } catch {
      // Safari 的部分版本无法从 File 创建 ImageBitmap，继续使用 img 解码。
    }
  }

  const objectUrl = URL.createObjectURL(file)
  const image = new Image()
  image.decoding = 'async'
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('图片解码失败'))
      image.src = objectUrl
    })
  } catch (error) {
    URL.revokeObjectURL(objectUrl)
    throw error
  }
  return {
    source: image,
    width: image.naturalWidth,
    height: image.naturalHeight,
    release: () => URL.revokeObjectURL(objectUrl),
  }
}

function canvasToBlob(canvas: HTMLCanvasElement, mimeType: string, quality?: number) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob || blob.type !== mimeType) {
        reject(new Error('浏览器无法按目标格式压缩图片'))
        return
      }
      resolve(blob)
    }, mimeType, quality)
  })
}

async function prepareImageForUpload(file: File) {
  let decoded: DecodedImage | null = null
  let canvas: HTMLCanvasElement | null = null
  try {
    decoded = await decodeImage(file)
    if (!decoded.width || !decoded.height) throw new Error('图片尺寸无效')
    const scale = Math.min(1, HARD_MAX_IMAGE_EDGE / Math.max(decoded.width, decoded.height))
    const needsResize = scale < 1
    const needsLossyReencode = file.type === 'image/jpeg' || file.type === 'image/webp'
    if (!needsResize && !needsLossyReencode) return file

    canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(decoded.width * scale))
    canvas.height = Math.max(1, Math.round(decoded.height * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器无法创建图片画布')
    context.drawImage(decoded.source, 0, 0, canvas.width, canvas.height)
    const blob = await canvasToBlob(
      canvas,
      file.type,
      needsLossyReencode ? LOSSY_IMAGE_QUALITY : undefined,
    )
    return new File([blob], file.name, { type: file.type, lastModified: file.lastModified })
  } catch {
    // 图片仍交由后端做真实格式和大小校验，前端处理失败不阻断正常上传。
    return file
  } finally {
    decoded?.release()
    if (canvas) {
      // 清空画布可更早释放移动端浏览器持有的像素缓冲区。
      canvas.width = 1
      canvas.height = 1
    }
  }
}

async function handleImageSelection(event: Event) {
  const input = event.target as HTMLInputElement
  const selectedFiles = Array.from(input.files || [])
  input.value = ''
  if (!selectedFiles.length || imageActionDisabled.value) return

  const fingerprints = new Set(localImages.value.map(
    (entry) => `${entry.file.name}:${entry.file.size}:${entry.file.lastModified}`,
  ))
  const accepted: File[] = []
  let firstError = ''
  for (const file of selectedFiles) {
    const error = validateImageType(file)
    const fingerprint = `${file.name}:${file.size}:${file.lastModified}`
    if (error) {
      firstError ||= `${file.name}：${error}`
      continue
    }
    if (fingerprints.has(fingerprint)) {
      firstError ||= `${file.name} 已经添加`
      continue
    }
    fingerprints.add(fingerprint)
    accepted.push(file)
  }

  if (accepted.length > remainingImageSlots.value) {
    firstError ||= `每次最多添加 ${imageLimit.value} 张图片`
    accepted.splice(remainingImageSlots.value)
  }
  if (!accepted.length) {
    if (firstError) ElMessage.warning(firstError)
    return
  }

  imagePreparing.value = true
  const preparedFiles: File[] = []
  try {
    for (const file of accepted) {
      const prepared = await prepareImageForUpload(file)
      if (disposed) return
      const error = validatePreparedImage(prepared)
      if (error) {
        firstError ||= `${file.name}：${error}`
        continue
      }
      preparedFiles.push(prepared)
    }
  } finally {
    imagePreparing.value = false
  }
  if (firstError) ElMessage.warning(firstError)
  if (!preparedFiles.length || disposed) return

  const entries = preparedFiles.map<LocalImageEntry>((file) => ({
    key: `image-${Date.now()}-${imageSequence += 1}`,
    file,
    previewUrl: URL.createObjectURL(file),
    assetId: null,
    status: 'queued',
    progress: 0,
    error: '',
    controller: null,
    removed: false,
  }))
  localImages.value.push(...entries)

  // 顺序上传，避免两张图片同时占用小服务器的请求和文件缓冲区。
  for (const entry of entries) {
    if (!entry.removed) await uploadImage(entry)
  }
}

async function uploadImage(entry: LocalImageEntry) {
  if (entry.removed) return
  const controller = new AbortController()
  entry.controller = controller
  entry.status = 'uploading'
  entry.progress = 0
  entry.error = ''
  try {
    const response = await aiMediaApi.uploadAsset(entry.file, {
      courseId: props.courseId,
      chapterId: props.chapterId,
      signal: controller.signal,
      onProgress: (percent) => { entry.progress = percent },
    })
    const asset = response.data.data
    if (entry.removed || disposed) {
      try { await aiMediaApi.deleteAsset(asset.id) } catch { /* 由服务端生命周期策略兜底清理 */ }
      return
    }
    entry.assetId = asset.id
    entry.status = 'ready'
    entry.progress = 100
    addAsset(asset)
  } catch (error) {
    if (entry.removed || isCanceled(error)) return
    entry.status = 'failed'
    entry.error = getErrorMessage(error, '图片上传失败，请重试')
  } finally {
    entry.controller = null
  }
}

async function removeImage(entry: LocalImageEntry) {
  if (entry.status === 'uploading' || entry.status === 'queued' || entry.status === 'failed' || entry.assetId == null) {
    releaseImageEntry(entry)
    return
  }
  await deleteAsset(entry.assetId, entry)
}

async function deleteAsset(assetId: number, localEntry?: LocalImageEntry) {
  if (deletingAssetIds.value.has(assetId)) return
  setDeleting(assetId, true)
  transcriptionControllers.get(assetId)?.abort()
  transcriptionControllers.delete(assetId)
  setTranscriptionState(assetId, null)
  try {
    await aiMediaApi.deleteAsset(assetId)
    removeAssetFromModel(assetId)
    if (localEntry) releaseImageEntry(localEntry)
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '附件删除失败，请稍后重试'))
  } finally {
    setDeleting(assetId, false)
  }
}

function preferredAudioMimeType() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ]
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || ''
}

function audioExtension(mimeType: string) {
  if (mimeType.includes('mp4')) return 'm4a'
  if (mimeType.includes('ogg')) return 'ogg'
  return 'webm'
}

function microphoneError(error: unknown) {
  if (error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'SecurityError')) {
    return '没有麦克风权限，请在浏览器设置中允许后重试'
  }
  if (error instanceof DOMException && error.name === 'NotFoundError') return '没有检测到可用麦克风'
  return getErrorMessage(error, '无法启动录音，请检查麦克风后重试')
}

async function startRecording() {
  if (audioActionDisabled.value) return
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    })
    if (disposed) {
      stream.getTracks().forEach((track) => track.stop())
      return
    }
    mediaStream = stream
    const mimeType = preferredAudioMimeType()
    const currentRecorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream)
    const chunks: BlobPart[] = []
    let recorderFailed = false
    recorder = currentRecorder
    recordingStartedAt = Date.now()
    recordingElapsedMs.value = 0

    currentRecorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data)
    }
    currentRecorder.onerror = () => {
      recorderFailed = true
      ElMessage.error('录音过程出现异常，请重新录制')
      if (currentRecorder.state !== 'inactive') currentRecorder.stop()
    }
    currentRecorder.onstop = () => {
      const durationSeconds = Math.min(
        maxAudioSeconds.value,
        Math.max(0, (Date.now() - recordingStartedAt) / 1000),
      )
      const actualMimeType = currentRecorder.mimeType || mimeType || 'audio/webm'
      releaseRecorderResources()
      if (disposed || recorderFailed) return
      const blob = new Blob(chunks, { type: actualMimeType })
      if (!blob.size) {
        ElMessage.warning('没有录到有效声音，请重新录制')
        return
      }
      void uploadRecording(blob, actualMimeType, durationSeconds)
    }

    currentRecorder.start(500)
    recording.value = true
    recordingTimer = setInterval(() => {
      recordingElapsedMs.value = Math.min(
        Date.now() - recordingStartedAt,
        maxAudioSeconds.value * 1000,
      )
      if (recordingElapsedMs.value >= maxAudioSeconds.value * 1000) stopRecording()
    }, 200)
  } catch (error) {
    releaseRecorderResources()
    ElMessage.error(microphoneError(error))
  }
}

function stopRecording() {
  if (!recorder || recorder.state === 'inactive') return
  recordingElapsedMs.value = Math.min(
    Date.now() - recordingStartedAt,
    maxAudioSeconds.value * 1000,
  )
  recording.value = false
  if (recordingTimer) clearInterval(recordingTimer)
  recordingTimer = null
  recorder.stop()
}

function releaseRecorderResources() {
  if (recordingTimer) clearInterval(recordingTimer)
  recordingTimer = null
  mediaStream?.getTracks().forEach((track) => track.stop())
  mediaStream = null
  recorder = null
  recording.value = false
}

async function uploadRecording(blob: Blob, mimeType: string, durationSeconds: number) {
  if (maxAudioBytes.value <= 0 || blob.size > maxAudioBytes.value) {
    ElMessage.error(`录音不能超过 ${formatLimit(capabilities.value?.max_audio_mb ?? 0)} MB`)
    return
  }
  const filename = `voice-${new Date().toISOString().replace(/[:.]/g, '-')}.${audioExtension(mimeType)}`
  const file = new File([blob], filename, { type: mimeType })
  const controller = new AbortController()
  audioUploadController = controller
  audioUploadTask.value = { filename, status: 'uploading', progress: 0, error: '' }
  try {
    const response = await aiMediaApi.uploadAsset(file, {
      courseId: props.courseId,
      chapterId: props.chapterId,
      durationSeconds: Math.max(0.01, Number(durationSeconds.toFixed(2))),
      signal: controller.signal,
      onProgress: (percent) => {
        if (audioUploadTask.value) audioUploadTask.value.progress = percent
      },
    })
    if (disposed) {
      try { await aiMediaApi.deleteAsset(response.data.data.id) } catch { /* 由服务端生命周期策略兜底清理 */ }
      return
    }
    const asset = response.data.data
    addAsset(asset)
    audioUploadTask.value = null
    await transcribe(asset)
  } catch (error) {
    if (disposed || isCanceled(error)) return
    audioUploadTask.value = {
      filename,
      status: 'failed',
      progress: 0,
      error: getErrorMessage(error, '录音上传失败，请重新录制'),
    }
  } finally {
    if (audioUploadController === controller) audioUploadController = null
  }
}

async function transcribe(asset: AiMediaAsset) {
  if (transcriptionStates.value[asset.id]?.status === 'transcribing') return
  const controller = new AbortController()
  transcriptionControllers.set(asset.id, controller)
  setTranscriptionState(asset.id, { status: 'transcribing', error: '' })
  try {
    const response = await aiMediaApi.transcribeAsset(asset.id, controller.signal)
    const text = response.data.data.text.trim()
    setTranscriptionState(asset.id, null)
    if (text) {
      emit('transcribed', text)
      ElMessage.success('语音已转成文字，可继续编辑后发送')
      // 语音只用于一次转写，成功后立即清理服务端临时文件和资产记录。
      await deleteAsset(asset.id)
    } else {
      setTranscriptionState(asset.id, { status: 'failed', error: '没有识别到有效文字，请重试' })
    }
  } catch (error) {
    if (isCanceled(error)) return
    setTranscriptionState(asset.id, {
      status: 'failed',
      error: getErrorMessage(error, '语音转写失败，请重试'),
    })
  } finally {
    if (transcriptionControllers.get(asset.id) === controller) {
      transcriptionControllers.delete(asset.id)
    }
  }
}

function dismissAudioUploadError() {
  audioUploadTask.value = null
}

watch(
  () => assets.value.map((asset) => asset.id),
  (assetIds) => {
    const currentIds = new Set(assetIds)
    for (const entry of [...localImages.value]) {
      if (entry.assetId != null && !currentIds.has(entry.assetId)) releaseImageEntry(entry)
    }
  },
)

onMounted(() => { void loadCapabilities() })

onBeforeUnmount(() => {
  emit('busy-changed', false)
  disposed = true
  audioUploadController?.abort()
  for (const controller of transcriptionControllers.values()) controller.abort()
  transcriptionControllers.clear()
  if (recorder && recorder.state !== 'inactive') {
    recorder.onstop = null
    recorder.stop()
  }
  releaseRecorderResources()
  for (const entry of [...localImages.value]) releaseImageEntry(entry)
})
</script>

<template>
  <section class="ai-media-composer" aria-label="图片和语音输入">
    <input
      ref="imageInput"
      class="visually-hidden"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      multiple
      :disabled="imageActionDisabled"
      aria-label="选择图片"
      @change="handleImageSelection"
    >
    <input
      ref="cameraInput"
      class="visually-hidden"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      capture="environment"
      :disabled="imageActionDisabled"
      aria-label="拍照"
      @change="handleImageSelection"
    >

    <div class="media-actions">
      <el-tooltip :content="imageActionHint" placement="top">
        <span class="action-wrapper">
          <el-button
            size="small"
            plain
            :icon="Picture"
            :disabled="imageActionDisabled"
            aria-label="选择图片"
            aria-describedby="ai-media-capability-hint"
            @click="openImagePicker"
          >图片</el-button>
        </span>
      </el-tooltip>
      <el-tooltip :content="imageActionHint" placement="top">
        <span class="action-wrapper">
          <el-button
            size="small"
            plain
            :icon="Camera"
            :disabled="imageActionDisabled"
            aria-label="使用相机拍照"
            aria-describedby="ai-media-capability-hint"
            @click="openCamera"
          >拍照</el-button>
        </span>
      </el-tooltip>
      <el-tooltip v-if="!recording" :content="audioActionHint" placement="top">
        <span class="action-wrapper">
          <el-button
            size="small"
            plain
            :icon="Microphone"
            :disabled="audioActionDisabled"
            aria-label="开始录音"
            aria-describedby="ai-media-capability-hint"
            @click="startRecording"
          >语音</el-button>
        </span>
      </el-tooltip>
      <el-button
        v-else
        size="small"
        type="danger"
        plain
        :icon="VideoPause"
        aria-label="停止录音"
        @click="stopRecording"
      >停止 {{ recordingTime }}</el-button>
      <span v-if="capabilities?.image_enabled" class="media-limit">
        图片 {{ selectedImageCount }}/{{ imageLimit }}
      </span>
    </div>

    <div v-if="recording" class="recording-status" role="status" aria-live="polite">
      <span class="recording-dot" aria-hidden="true"></span>
      <strong>正在录音 {{ recordingTime }}</strong>
      <span>最长 {{ maxAudioSeconds }} 秒，到时自动停止</span>
    </div>

    <p
      v-if="capabilityHint"
      id="ai-media-capability-hint"
      class="capability-hint"
      :class="{ error: Boolean(capabilityError) }"
      role="status"
    >
      <span>{{ capabilityHint }}</span>
      <el-button v-if="capabilityError" text type="primary" size="small" @click="loadCapabilities">
        重新检测
      </el-button>
    </p>

    <div v-if="localImages.length || imagesWithoutLocalPreview.length" class="image-list" aria-label="已添加图片">
      <figure
        v-for="entry in localImages"
        :key="entry.key"
        class="image-card"
        :class="`is-${entry.status}`"
        :aria-busy="entry.status === 'uploading'"
      >
        <img :src="entry.previewUrl" :alt="`${entry.file.name} 预览`">
        <figcaption>
          <strong :title="entry.file.name">{{ entry.file.name }}</strong>
          <span v-if="entry.status === 'queued'">等待上传</span>
          <span v-else-if="entry.status === 'uploading'">上传中 {{ entry.progress }}%</span>
          <span v-else-if="entry.status === 'ready'">已上传 · {{ formatFileSize(entry.file.size) }}</span>
          <span v-else class="error-text" :title="entry.error">{{ entry.error }}</span>
        </figcaption>
        <div class="image-card-actions">
          <el-button
            v-if="entry.status === 'failed'"
            circle
            text
            size="small"
            :icon="RefreshRight"
            :disabled="imageTransferBusy"
            aria-label="重新上传图片"
            @click="uploadImage(entry)"
          />
          <el-button
            circle
            text
            size="small"
            :icon="Delete"
            :loading="entry.assetId != null && deletingAssetIds.has(entry.assetId)"
            :aria-label="`删除图片 ${entry.file.name}`"
            @click="removeImage(entry)"
          />
        </div>
        <el-progress
          v-if="entry.status === 'uploading'"
          class="upload-progress"
          :percentage="entry.progress"
          :show-text="false"
          :stroke-width="3"
        />
      </figure>

      <figure v-for="asset in imagesWithoutLocalPreview" :key="asset.id" class="image-card stored-image">
        <div class="stored-image-placeholder" aria-hidden="true"><el-icon><Picture /></el-icon></div>
        <figcaption>
          <strong :title="asset.original_filename">{{ asset.original_filename }}</strong>
          <span>已上传 · {{ formatFileSize(asset.byte_size) }}</span>
        </figcaption>
        <div class="image-card-actions">
          <el-button
            circle
            text
            size="small"
            :icon="Delete"
            :loading="deletingAssetIds.has(asset.id)"
            :aria-label="`删除图片 ${asset.original_filename}`"
            @click="deleteAsset(asset.id)"
          />
        </div>
      </figure>
    </div>

    <div v-if="audioUploadTask || audioAssets.length" class="audio-list" aria-label="语音附件">
      <div v-if="audioUploadTask" class="audio-card" :class="{ failed: audioUploadTask.status === 'failed' }" role="status">
        <el-icon><Microphone /></el-icon>
        <div>
          <strong>{{ audioUploadTask.filename }}</strong>
          <span v-if="audioUploadTask.status === 'uploading'">上传中 {{ audioUploadTask.progress }}%</span>
          <span v-else class="error-text">{{ audioUploadTask.error }}</span>
        </div>
        <el-button
          v-if="audioUploadTask.status === 'failed'"
          circle
          text
          size="small"
          :icon="Delete"
          aria-label="移除失败录音"
          @click="dismissAudioUploadError"
        />
      </div>

      <div v-for="asset in audioAssets" :key="asset.id" class="audio-card">
        <el-icon><Microphone /></el-icon>
        <div>
          <strong :title="asset.original_filename">{{ asset.original_filename }}</strong>
          <span v-if="transcriptionStates[asset.id]?.status === 'transcribing'">正在转成文字…</span>
          <span v-else-if="transcriptionStates[asset.id]?.status === 'failed'" class="error-text">
            {{ transcriptionStates[asset.id].error }}
          </span>
          <span v-else>{{ formatDuration(asset.duration_seconds) }} · {{ formatFileSize(asset.byte_size) }}</span>
        </div>
        <div class="audio-card-actions">
          <el-button
            v-if="transcriptionStates[asset.id]?.status === 'failed'"
            circle
            text
            size="small"
            :icon="RefreshRight"
            aria-label="重新转写语音"
            @click="transcribe(asset)"
          />
          <el-button
            circle
            text
            size="small"
            :icon="Delete"
            :loading="deletingAssetIds.has(asset.id)"
            :aria-label="`删除录音 ${asset.original_filename}`"
            @click="deleteAsset(asset.id)"
          />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.ai-media-composer {
  display: grid;
  gap: 8px;
  color: #425573;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  padding: 0;
  margin: -1px;
  white-space: nowrap;
  border: 0;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
}

.media-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.action-wrapper {
  display: inline-flex;
}

.media-actions :deep(.el-button) {
  margin: 0;
  border-radius: 8px;
}

.media-limit {
  margin-left: auto;
  color: #8a98ad;
  font-size: 11px;
}

.capability-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0;
  padding: 6px 8px;
  color: #7b879a;
  background: #f7f9fc;
  border-radius: 7px;
  font-size: 11px;
  line-height: 1.45;
}

.capability-hint.error {
  color: #9b5f17;
  background: #fff8e9;
}

.capability-hint :deep(.el-button) {
  flex: 0 0 auto;
  padding: 2px 4px;
}

.recording-status {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  color: #9f3142;
  background: #fff4f5;
  border: 1px solid #f0ccd1;
  border-radius: 9px;
  font-size: 11px;
}

.recording-status > span:last-child {
  margin-left: auto;
  color: #a8757d;
}

.recording-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  background: #d34556;
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgba(211, 69, 86, .12);
  animation: recording-pulse 1s ease-in-out infinite;
}

@keyframes recording-pulse {
  50% { opacity: .45; transform: scale(.8); }
}

.image-list,
.audio-list {
  display: grid;
  gap: 7px;
}

.image-list {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.image-card {
  position: relative;
  display: grid;
  min-width: 0;
  grid-template-columns: 54px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  overflow: hidden;
  margin: 0;
  padding: 7px;
  background: #fbfcff;
  border: 1px solid #dfe7f3;
  border-radius: 10px;
}

.image-card.is-failed {
  border-color: #efc3c9;
}

.image-card img,
.stored-image-placeholder {
  width: 54px;
  height: 46px;
  object-fit: cover;
  background: #eef2f8;
  border-radius: 7px;
}

.stored-image-placeholder {
  display: grid;
  place-items: center;
  color: #7589ae;
  font-size: 21px;
}

.image-card figcaption,
.audio-card > div:not(.audio-card-actions) {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.image-card figcaption strong,
.audio-card strong {
  overflow: hidden;
  color: #354967;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.image-card figcaption span,
.audio-card span {
  overflow: hidden;
  color: #8794a8;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.image-card-actions,
.audio-card-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
}

.image-card-actions :deep(.el-button),
.audio-card-actions :deep(.el-button),
.audio-card > :deep(.el-button) {
  margin: 0;
  color: #71809a;
}

.image-card-actions :deep(.el-button:hover),
.audio-card-actions :deep(.el-button:hover),
.audio-card > :deep(.el-button:hover) {
  color: #c0394b;
  background: #fff0f2;
}

.upload-progress {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
}

.audio-card {
  display: grid;
  min-width: 0;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: #f7f9ff;
  border: 1px solid #dfe6f4;
  border-radius: 9px;
}

.audio-card.failed {
  border-color: #efc3c9;
}

.audio-card > .el-icon {
  color: #4f6dd5;
  font-size: 18px;
}

.error-text {
  color: #b33c49 !important;
}

@media (max-width: 560px) {
  .image-list { grid-template-columns: 1fr; }
  .recording-status { flex-wrap: wrap; }
  .recording-status > span:last-child { width: 100%; margin-left: 15px; }
}

@media (prefers-reduced-motion: reduce) {
  .recording-dot { animation: none; }
}
</style>
