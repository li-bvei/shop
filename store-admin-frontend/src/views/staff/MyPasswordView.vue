<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { changeOwnPassword } from '@/api/accounts'

const { t } = useI18n()

const passwordFormRef = ref<FormInstance>()
const passwordSubmitting = ref(false)
const passwordForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const passwordRules = computed<FormRules>(() => ({
  oldPassword: [{ required: true, message: t('settings.validateOldPassword'), trigger: 'blur' }],
  newPassword: [
    { required: true, message: t('settings.validateNewPassword'), trigger: 'blur' },
    { min: 6, message: t('settings.validatePasswordLength'), trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: t('settings.validateConfirmPassword'), trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        callback(value === passwordForm.newPassword ? undefined : new Error(t('settings.passwordMismatch')))
      },
      trigger: 'blur',
    },
  ],
}))

async function handleChangePassword() {
  if (!passwordFormRef.value) return
  await passwordFormRef.value.validate(async (valid) => {
    if (!valid) return
    passwordSubmitting.value = true
    try {
      await changeOwnPassword(passwordForm.oldPassword, passwordForm.newPassword)
      ElMessage.success(t('settings.passwordChangedSuccess'))
      passwordForm.oldPassword = ''
      passwordForm.newPassword = ''
      passwordForm.confirmPassword = ''
      passwordFormRef.value?.clearValidate()
    } catch (err) {
      if (err instanceof Error && err.message === 'invalid-old-password') {
        ElMessage.error(t('settings.invalidOldPassword'))
      }
    } finally {
      passwordSubmitting.value = false
    }
  })
}
</script>

<template>
  <div class="my-password-view">
    <div class="card">
      <h3>{{ t('settings.changePasswordSection') }}</h3>
      <p class="section-hint">{{ t('settings.changePasswordHint') }}</p>
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-position="top" class="password-form">
        <el-form-item :label="t('settings.oldPassword')" prop="oldPassword">
          <el-input v-model="passwordForm.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('settings.newPassword')" prop="newPassword">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('settings.confirmPassword')" prop="confirmPassword">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
        </el-form-item>
        <el-button type="primary" :loading="passwordSubmitting" @click="handleChangePassword">
          {{ t('settings.changePasswordSubmit') }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.my-password-view .card h3 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px;
}

.section-hint {
  font-size: 12.5px;
  color: var(--text-tertiary);
  margin: 0 0 16px;
}

.password-form {
  max-width: 320px;
}
</style>
