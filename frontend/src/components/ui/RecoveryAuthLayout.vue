<script setup lang="ts">
import { ArrowRight, CircleCheckFilled, Message } from '@element-plus/icons-vue'
import BrandLockup from '@/components/ui/BrandLockup.vue'

withDefaults(defineProps<{
  activeStep: 1 | 2 | 3
  eyebrow?: string
  title: string
  description: string
  railTitle?: string
  railDescription?: string
  visual?: 'message' | 'success'
}>(), {
  eyebrow: '账户恢复',
  railTitle: '找回你的学习空间',
  railDescription: '通过验证账号信息，安全地恢复访问权限。',
  visual: 'message',
})

const steps = [
  { number: '01', title: '验证账号', description: '确认账号与邮箱' },
  { number: '02', title: '设置密码', description: '创建新的登录密码' },
  { number: '03', title: '完成', description: '重新进入学习空间' },
]
</script>

<template>
  <main class="recovery-auth-page">
    <section class="recovery-auth-rail" aria-label="密码恢复流程">
      <div class="recovery-rail-brand">
        <BrandLockup title="思政红芯" subtitle="思政智教 · 思政教学平台" />
      </div>

      <div class="recovery-rail-content">
        <p class="recovery-rail-kicker">安全访问</p>
        <h1>{{ railTitle }}</h1>
        <p class="recovery-rail-description">{{ railDescription }}</p>

        <ol class="recovery-steps">
          <li
            v-for="(step, index) in steps"
            :key="step.number"
            class="recovery-step"
            :class="{ 'is-active': index + 1 === activeStep, 'is-complete': index + 1 < activeStep }"
          >
            <span class="recovery-step-marker">
              <svg v-if="index + 1 < activeStep" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.2 8.3 3.1 3.1 6.5-6.8" /></svg>
              <span v-else>{{ step.number }}</span>
            </span>
            <span class="recovery-step-copy">
              <strong>{{ step.title }}</strong>
              <small>{{ step.description }}</small>
            </span>
          </li>
        </ol>
      </div>

      <button type="button" class="recovery-rail-footer" aria-describedby="recovery-help-tooltip">
        <span>需要帮助？请联系平台管理员</span>
        <span id="recovery-help-tooltip" class="recovery-help-tooltip" role="tooltip">
          <small>联系邮箱</small>
          <strong>2687590637@qq.com</strong>
        </span>
      </button>
    </section>

    <section class="recovery-auth-panel" aria-labelledby="recovery-title">
      <div class="recovery-panel-body">
        <div class="recovery-panel-icon" :class="{ 'is-success': visual === 'success' }" aria-hidden="true">
          <span class="recovery-panel-icon-core">
            <el-icon v-if="visual === 'success'"><CircleCheckFilled /></el-icon>
            <el-icon v-else><Message /></el-icon>
          </span>
        </div>
        <div class="recovery-panel-heading">
          <p class="recovery-eyebrow">{{ eyebrow }}</p>
          <h2 id="recovery-title">{{ title }}</h2>
          <p>{{ description }}</p>
        </div>
        <slot />
        <slot name="footer">
          <div class="recovery-panel-footer">
            <router-link to="/login">返回登录</router-link>
            <router-link to="/register">注册账号 <el-icon><ArrowRight /></el-icon></router-link>
          </div>
        </slot>
      </div>
    </section>
  </main>
</template>

<style scoped>
.recovery-auth-page {
  display: grid;
  width: 100%;
  min-height: 100dvh;
  grid-template-columns: minmax(430px, 42.1%) minmax(0, 1fr);
  background: #fff;
}

.recovery-auth-rail {
  position: relative;
  display: flex;
  min-height: 100dvh;
  flex-direction: column;
  overflow: hidden;
  padding: clamp(34px, 5.2vh, 58px) clamp(42px, 5.5vw, 86px) 32px;
  background: #ffebec;
}

.recovery-auth-rail::before,
.recovery-auth-rail::after {
  position: absolute;
  content: '';
  pointer-events: none;
  border: 1px solid rgba(243, 69, 65, .12);
  border-radius: 50%;
}

.recovery-auth-rail::before {
  right: -190px;
  bottom: -200px;
  width: 520px;
  height: 520px;
}

.recovery-auth-rail::after {
  right: -115px;
  bottom: -128px;
  width: 370px;
  height: 370px;
}

.recovery-rail-brand,
.recovery-rail-content,
.recovery-rail-footer { position: relative; z-index: 1; }

.recovery-rail-brand :deep(.brand-lockup__mark) {
  width: 46px;
  height: 46px;
  background: rgba(255, 255, 255, .78);
  border-color: rgba(243, 69, 65, .16);
  border-radius: 13px;
}

.recovery-rail-brand :deep(.brand-lockup__copy strong) { color: #3c2028; }
.recovery-rail-brand :deep(.brand-lockup__copy small) { color: #9b666d; }

.recovery-rail-content { max-width: 410px; margin-top: clamp(72px, 13vh, 146px); }
.recovery-rail-kicker,
.recovery-eyebrow {
  margin: 0 0 14px;
  color: #d04446;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .16em;
  line-height: 1.4;
}

.recovery-rail-content h1 {
  max-width: 340px;
  margin: 0;
  color: #3a2027;
  font-size: clamp(31px, 3.1vw, 48px);
  font-weight: 720;
  letter-spacing: 0;
  line-height: 1.2;
}

.recovery-rail-description {
  max-width: 330px;
  margin: 18px 0 0;
  color: #8d6269;
  font-size: 15px;
  line-height: 1.8;
}

.recovery-steps {
  position: relative;
  display: grid;
  gap: 28px;
  margin: 54px 0 0;
  padding: 0;
  list-style: none;
}

.recovery-steps::before {
  position: absolute;
  top: 19px;
  bottom: 19px;
  left: 20px;
  width: 1px;
  content: '';
  background: #e4c5c9;
}

.recovery-step { position: relative; display: flex; align-items: center; gap: 16px; min-height: 42px; }
.recovery-step-marker {
  position: relative;
  z-index: 1;
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  place-items: center;
  color: #b4787e;
  background: #ffebec;
  border: 1px solid #e4c5c9;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 750;
}

.recovery-step.is-active .recovery-step-marker {
  color: #fff;
  background: #f34541;
  border-color: #f34541;
  box-shadow: 0 7px 16px rgba(243, 69, 65, .2);
}

.recovery-step.is-complete .recovery-step-marker { color: #fff; background: #dc6d6d; border-color: #dc6d6d; }
.recovery-step-marker svg { width: 17px; height: 17px; fill: none; stroke: currentcolor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; }
.recovery-step-copy { display: grid; gap: 4px; }
.recovery-step-copy strong { color: #55353b; font-size: 15px; font-weight: 700; }
.recovery-step-copy small { color: #ad7c83; font-size: 12px; line-height: 1.4; }
.recovery-step.is-active .recovery-step-copy strong { color: #d33d40; }

.recovery-rail-footer { position: relative; width: fit-content; margin: auto 0 0; padding: 0; color: #ad7c83; background: transparent; border: 0; cursor: help; font: inherit; font-size: 12px; text-align: left; }
.recovery-rail-footer:hover,
.recovery-rail-footer:focus-visible { color: #d04446; }
.recovery-help-tooltip { position: absolute; bottom: calc(100% + 13px); left: 0; display: grid; min-width: 224px; gap: 4px; padding: 12px 14px; color: #6e4c54; background: rgba(255, 255, 255, .97); border: 1px solid #f0c8cc; border-radius: 9px; box-shadow: 0 12px 28px rgba(143, 68, 77, .16); opacity: 0; pointer-events: none; transform: translateY(6px); transition: opacity .18s ease, transform .18s ease; }
.recovery-help-tooltip::after { position: absolute; bottom: -6px; left: 22px; width: 10px; height: 10px; content: ''; background: #fff; border-right: 1px solid #f0c8cc; border-bottom: 1px solid #f0c8cc; transform: rotate(45deg); }
.recovery-help-tooltip small { color: #aa7b82; font-size: 11px; }
.recovery-help-tooltip strong { color: #d04446; font-size: 14px; font-weight: 700; letter-spacing: .01em; }
.recovery-rail-footer:hover .recovery-help-tooltip,
.recovery-rail-footer:focus-visible .recovery-help-tooltip { opacity: 1; pointer-events: auto; transform: translateY(0); }

.recovery-auth-panel { display: flex; min-width: 0; flex-direction: column; overflow-y: auto; background: #fff; }
.recovery-panel-body { width: min(100%, 510px); margin: 0 auto; padding: 102px 32px 42px; }
.recovery-panel-icon { position: relative; display: grid; width: 120px; height: 120px; place-items: center; margin: 0 auto 36px; background: linear-gradient(145deg, #ffc1c9 4%, #ff858d 46%, #ff9a9e 100%); border: 1px solid #8ecbff; border-radius: 50%; box-shadow: 0 0 0 5px rgba(143, 203, 255, .08), 0 8px 22px rgba(80, 166, 230, .24); }
.recovery-panel-icon::before { position: absolute; width: 80px; height: 80px; content: ''; background: linear-gradient(160deg, #ffdc72 0%, #ff724f 42%, #ff2146 100%); border-radius: 50%; box-shadow: inset 0 2px 10px rgba(255, 255, 255, .24); }
.recovery-panel-icon-core { position: relative; z-index: 1; display: grid; width: 49px; height: 49px; place-items: center; color: #fff; }
.recovery-panel-icon-core .el-icon { font-size: 36px; }
.recovery-panel-icon.is-success::before { background: linear-gradient(160deg, #ffbf61 0%, #f75a4e 45%, #e63c42 100%); }
.recovery-panel-heading { margin-bottom: 27px; text-align: center; }
.recovery-eyebrow { display: none; }
.recovery-panel-heading h2 { margin: 0 0 15px; color: #1e0d2c; font-size: clamp(30px, 3.2vw, 42px); font-weight: 760; letter-spacing: 0; line-height: 1.25; }
.recovery-panel-heading > p:last-child { max-width: 460px; margin: 0 auto; color: #594173; font-size: 16px; line-height: 1.7; }

:deep(.recovery-form .el-form-item) { margin-bottom: 18px; }
:deep(.recovery-form .el-form-item__label) { padding-bottom: 8px; color: #594173; font-size: 15px; font-weight: 650; line-height: 1.4; }
:deep(.recovery-form .el-input__wrapper) { min-height: 52px; padding: 1px 16px; background: #fff; border: 1px solid #e6deeb; border-radius: 13px; box-shadow: 0 3px 9px rgba(73, 52, 101, .08); transition: border-color .18s ease, box-shadow .18s ease; }
:deep(.recovery-form .el-input__wrapper:hover) { border-color: #c5b3d0; }
:deep(.recovery-form .el-input__wrapper.is-focus) { border-color: #f06a67; box-shadow: 0 0 0 3px rgba(243, 69, 65, .11), 0 4px 10px rgba(73, 52, 101, .08); }
:deep(.recovery-form .el-input__inner) { color: #34252a; font-size: 15px; }
:deep(.recovery-form .el-input__inner::placeholder) { color: #b9adb1; }
:deep(.recovery-form .el-input__prefix-inner > .el-icon) { color: #694c83; font-size: 19px; }
:deep(.recovery-form .el-form-item__error) { padding-top: 5px; color: #d84d4d; }

:deep(.recovery-submit) { width: 100%; height: 50px; margin-top: 6px; color: #fff; background: #f34541; border-color: #f34541; border-radius: 13px; font-size: 15px; font-weight: 700; letter-spacing: .03em; }
:deep(.recovery-submit:hover),
:deep(.recovery-submit:focus) { color: #fff; background: #dd3d3b; border-color: #dd3d3b; }
:deep(.recovery-submit:active) { background: #c93434; border-color: #c93434; }

.recovery-panel-footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 22px; color: #9f8d93; font-size: 13px; }
.recovery-panel-footer a { display: inline-flex; align-items: center; gap: 5px; color: #a06c70; }
.recovery-panel-footer a:hover { color: #d43f42; }
.recovery-panel-footer a:last-child { color: #d43f42; font-weight: 650; }

:deep(.recovery-notice) { margin: -8px 0 26px; padding: 13px 15px; color: #7d6368; background: #fff8f8; border: 1px solid #f2d9da; border-radius: 7px; font-size: 13px; line-height: 1.7; }
:deep(.recovery-notice strong) { color: #5a343a; font-weight: 700; }
:deep(.recovery-success) { display: grid; justify-items: start; gap: 12px; }
:deep(.recovery-success-mark) { display: grid; width: 56px; height: 56px; place-items: center; color: #fff; background: #f34541; border-radius: 50%; font-size: 25px; }
:deep(.recovery-success p) { margin: 0 0 12px; color: #8a7b80; font-size: 14px; line-height: 1.8; }
:deep(.recovery-muted-action) { margin-top: 18px; color: #a06c70; }

@media (max-width: 900px) {
  .recovery-auth-page { grid-template-columns: 1fr; }
  .recovery-auth-rail { min-height: auto; padding-bottom: 44px; }
  .recovery-rail-content { margin-top: 64px; }
  .recovery-rail-footer { margin-top: 52px; }
  .recovery-panel-body { padding-top: 72px; }
}
</style>
