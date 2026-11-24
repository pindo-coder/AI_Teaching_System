<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { agentApi } from '@/api/agents'

const props = defineProps<{ runId: number; slideIndex: number; revision: string; title: string; versionId?: string }>()
const src = ref('')
const loading = ref(false)
const error = ref(false)
let generation = 0
let controller: AbortController | undefined
function clear() {
  if (src.value) URL.revokeObjectURL(src.value)
  src.value = ''
}
async function load() {
  const current = ++generation
  controller?.abort()
  controller = new AbortController()
  clear()
  loading.value = true
  error.value = false
  try {
    const response = await agentApi.pptSlidePreview(props.runId, props.slideIndex, props.versionId,
      props.versionId ? undefined : props.revision, controller.signal)
    if (current !== generation) return
    src.value = URL.createObjectURL(response.data)
  } catch {
    if (current === generation) error.value = true
  } finally {
    if (current === generation) loading.value = false
  }
}
watch(() => [props.runId, props.slideIndex, props.revision, props.versionId], load, { immediate: true })
onBeforeUnmount(() => { generation++; controller?.abort(); clear() })
</script>

<template>
  <div class="ppt-file-preview" v-loading="loading">
    <img v-if="src" :src="src" :alt="`第 ${slideIndex + 1} 页：${title}`" />
    <div v-else-if="error" class="preview-error">
      成品预览暂不可用，可下载 PPT 查看。
      <el-button text @click="load">重试</el-button>
    </div>
    <span v-else>正在读取成品预览…</span>
  </div>
</template>

<style scoped>
.ppt-file-preview { width: 100%; aspect-ratio: 16 / 9; display: grid; place-items: center; background: #f4f5f7; color: #657080; overflow: hidden; }
.ppt-file-preview img { display: block; width: 100%; height: 100%; object-fit: contain; }
.preview-error { padding: 24px; text-align: center; }
</style>
