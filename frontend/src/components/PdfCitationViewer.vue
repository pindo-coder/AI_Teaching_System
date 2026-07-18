<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, WarningFilled } from '@element-plus/icons-vue'
import { knowledgeApi, type DocumentPage } from '@/api/knowledge'
import type { AiSource } from '@/api/ai'
import { getErrorMessage } from '@/utils/error'

const props = defineProps<{ visible: boolean; source: AiSource | null }>()
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const loading = ref(false)
const pageData = ref<DocumentPage | null>(null)
const pdfUrl = ref('')
const feedbackSent = ref(false)
const sourceTagType = computed(() => props.source?.material_type === 'central' ? 'danger' : props.source?.material_type === 'local' ? 'success' : 'primary')

const pageLabel = computed(() => {
  if (!props.source) return ''
  const printed = props.source.printed_page_start ? `印刷页 ${props.source.printed_page_start}` : ''
  const pdf = props.source.pdf_page_start ? `PDF 第 ${props.source.pdf_page_start} 页` : ''
  const paragraph = props.source.paragraph_index ? `第 ${props.source.paragraph_index} 段` : ''
  return [printed, pdf, paragraph].filter(Boolean).join(' · ')
})

const highlightedText = computed(() => {
  const text = pageData.value?.text || ''
  const excerpt = (props.source?.excerpt || '').replace(/……$/, '').trim()
  if (!text || !excerpt) return [{ text, hit: false }]
  let needle = excerpt
  let index = text.indexOf(needle)
  if (index < 0) {
    needle = excerpt.slice(0, Math.min(48, excerpt.length))
    index = text.indexOf(needle)
  }
  if (index < 0 || !needle) return [{ text, hit: false }]
  return [
    { text: text.slice(0, index), hit: false },
    { text: text.slice(index, index + needle.length), hit: true },
    { text: text.slice(index + needle.length), hit: false },
  ]
})

function revokePdf() {
  if (pdfUrl.value) URL.revokeObjectURL(pdfUrl.value)
  pdfUrl.value = ''
}

async function loadCitation() {
  revokePdf()
  pageData.value = null
  feedbackSent.value = false
  if (!props.visible || !props.source?.document_id || !props.source.pdf_page_start) return
  loading.value = true
  try {
    const [pages, file] = await Promise.all([
      knowledgeApi.pages(props.source.document_id, props.source.pdf_page_start),
      knowledgeApi.fileBlob(props.source.document_id, props.source.pdf_page_start),
    ])
    pageData.value = pages.data.data[0] || null
    pdfUrl.value = URL.createObjectURL(file.data)
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, '引用原页加载失败'))
  } finally {
    loading.value = false
  }
}

async function reportIssue() {
  if (!props.source || feedbackSent.value) return
  await knowledgeApi.citationFeedback({
    document_id: props.source.document_id || undefined,
    vector_id: props.source.vector_id || undefined,
    feedback_type: 'inaccurate',
    note: `用户在 ${pageLabel.value} 查看引用后标记为待核查`,
  })
  feedbackSent.value = true
  ElMessage.success('已记录，管理员可在后续校准中处理')
}

watch(() => [props.visible, props.source?.vector_id], loadCitation)
onBeforeUnmount(revokePdf)
</script>

<template>
  <el-dialog :model-value="visible" width="min(1180px, 94vw)" class="citation-dialog" destroy-on-close @update:model-value="emit('update:visible', $event)">
    <template #header>
      <div class="citation-dialog__header">
        <span class="citation-dialog__icon"><el-icon><Document /></el-icon></span>
        <div><strong>{{ source?.source_title }}</strong><p>{{ source?.section_path || source?.position }} · {{ pageLabel }}</p></div>
        <el-tag :type="sourceTagType">{{ source?.evidence_type }}</el-tag>
      </div>
    </template>
    <div v-loading="loading" class="citation-viewer">
      <section class="citation-viewer__pdf">
        <iframe v-if="pdfUrl" :src="`${pdfUrl}#toolbar=1&navpanes=0&view=FitH`" title="资料引用原页"></iframe>
        <el-empty v-else description="正在读取资料原页" />
      </section>
      <aside class="citation-viewer__text">
        <div class="citation-excerpt"><span>AI 使用的原文片段</span><p>{{ source?.excerpt }}</p></div>
        <div class="citation-page-text">
          <h3>本页可检索文字</h3>
          <p><template v-for="(part, index) in highlightedText" :key="index"><mark v-if="part.hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></p>
        </div>
        <el-alert v-if="!highlightedText.some((item) => item.hit)" :icon="WarningFilled" type="warning" :closable="false" title="PDF 排版可能导致文字坐标无法精确匹配，已定位到原页并保留引用片段供核对。" />
        <el-button plain :disabled="feedbackSent" @click="reportIssue">{{ feedbackSent ? '已提交引用反馈' : '引用位置有误' }}</el-button>
      </aside>
    </div>
  </el-dialog>
</template>
