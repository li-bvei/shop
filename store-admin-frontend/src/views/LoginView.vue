<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { House } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive({ account: '', password: '' })

const rules: FormRules = {
  account: [{ required: true, message: t('login.validateAccount'), trigger: 'blur' }],
  password: [{ required: true, message: t('login.validatePassword'), trigger: 'blur' }],
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      await auth.login(form.account, form.password)
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.push(redirect)
    } catch {
      ElMessage.error(t('login.invalidCredentials'))
    } finally {
      submitting.value = false
    }
  })
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-mark">
        <el-icon :size="28" color="#fff"><House /></el-icon>
      </div>
      <h1>{{ t('login.title') }}</h1>
      <p>{{ t('login.subtitle') }}</p>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="handleSubmit">
        <el-form-item :label="t('login.account')" prop="account">
          <el-input v-model="form.account" :placeholder="t('login.accountPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('login.password')" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="••••••••" />
        </el-form-item>
        <el-button type="primary" class="btn-primary" :loading="submitting" native-type="submit">
          {{ t('login.submit') }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}

.login-card {
  width: 360px;
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 40px 36px 32px;
  box-shadow: var(--shadow-card);
  text-align: center;
}

.login-mark {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 20px;
}

.login-card h1 {
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 4px;
  color: var(--text-primary);
}

.login-card p {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 28px;
}

.login-card :deep(.el-form-item) {
  text-align: left;
  margin-bottom: 14px;
}

.login-card :deep(.el-form-item__label) {
  font-size: 12px;
  color: var(--text-secondary);
  padding-bottom: 6px;
}

.login-card :deep(.el-input__inner) {
  height: 42px;
}

.btn-primary {
  width: 100%;
  height: 42px;
  font-size: 14px;
  margin-top: 8px;
}
</style>
