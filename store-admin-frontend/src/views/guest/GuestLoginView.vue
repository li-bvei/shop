<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api/http'
import { guestLogin, recoverCard, type RecoveryOption } from '@/api/guest'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

// Landed here because the phone typed on the register form already had a card.
const cameFromExisting = computed(() => route.query.existing === '1')

// 'pin'  — phone + birthday + 6-digit PIN, regain full use on a new device.
// 'view' — phone + birthday, read-only snapshot (no spending).
const mode = ref<'pin' | 'view'>('pin')
const form = reactive({ phone: '', pin: '', birthdayMonth: '', birthdayDay: '' })
const submitting = ref(false)
const errorMsg = ref('')
const pickerOptions = ref<RecoveryOption[] | null>(null)

const months = Array.from({ length: 12 }, (_, i) => i + 1)
const days = Array.from({ length: 31 }, (_, i) => i + 1)

const birthdayMd = computed(() =>
  form.birthdayMonth && form.birthdayDay
    ? `${String(form.birthdayMonth).padStart(2, '0')}-${String(form.birthdayDay).padStart(2, '0')}`
    : '',
)

const phoneOk = computed(() => form.phone.trim().length >= 10)
const canSubmit = computed(() => {
  if (submitting.value || !phoneOk.value || !birthdayMd.value) return false
  return mode.value === 'pin' ? /^\d{6}$/.test(form.pin) : true
})

const orgName = (o: RecoveryOption) => (locale.value === 'ja' ? o.orgNameJa : o.orgNameZh)

function switchMode(next: 'pin' | 'view') {
  mode.value = next
  errorMsg.value = ''
  pickerOptions.value = null
}

async function run(org?: string) {
  submitting.value = true
  errorMsg.value = ''
  try {
    const phone = form.phone.trim()
    if (mode.value === 'pin') {
      const r = await recoverCard(phone, birthdayMd.value, form.pin, org)
      if ('options' in r) {
        pickerOptions.value = r.options
        return
      }
      router.replace({ name: 'guest-card' })
    } else {
      const r = await guestLogin(phone, birthdayMd.value, org)
      if ('options' in r) {
        pickerOptions.value = r.options
        return
      }
      router.push({
        name: 'guest-card',
        query: { readonly: '1' },
        state: { phone, birthdayMd: birthdayMd.value, org: org ?? '' },
      })
    }
  } catch (err) {
    if (err instanceof ApiError) {
      const body = JSON.stringify(err.body)
      if (body.includes('pin-recovery-locked')) errorMsg.value = t('guest.errPinLocked')
      else if (mode.value === 'pin') errorMsg.value = t('guest.errPinWrong')
      else errorMsg.value = t('guest.loginFailed')
    } else {
      errorMsg.value = t('guest.errGeneric')
    }
    pickerOptions.value = null
  } finally {
    submitting.value = false
  }
}

function submit() {
  if (canSubmit.value) run()
}
</script>

<template>
  <div class="card">
    <h1>{{ t('guest.loginTitle') }}</h1>
    <p v-if="cameFromExisting" class="notice notice-info">{{ t('guest.existingHint') }}</p>

    <!-- merchant picker -->
    <template v-if="pickerOptions">
      <p class="lead">{{ t('guest.pickCardLead') }}</p>
      <div class="picker">
        <button
          v-for="o in pickerOptions"
          :key="o.org"
          type="button"
          class="picker-item"
          :disabled="submitting"
          @click="run(o.org)"
        >
          <img v-if="o.logoUrl" :src="o.logoUrl" alt="" class="picker-logo" />
          <span>{{ orgName(o) }}</span>
        </button>
      </div>
      <button type="button" class="text-btn" @click="pickerOptions = null">{{ t('common.back') }}</button>
    </template>

    <template v-else>
      <div class="mode-toggle">
        <button type="button" :class="{ active: mode === 'pin' }" @click="switchMode('pin')">
          {{ t('guest.modePin') }}
        </button>
        <button type="button" :class="{ active: mode === 'view' }" @click="switchMode('view')">
          {{ t('guest.modeView') }}
        </button>
      </div>
      <p class="lead">{{ mode === 'pin' ? t('guest.pinRecoverLead') : t('guest.loginLead') }}</p>

      <form class="form" @submit.prevent="submit">
        <label class="field">
          <span class="label">{{ t('guest.phone') }}</span>
          <input
            v-model="form.phone"
            type="tel"
            inputmode="numeric"
            autocomplete="tel"
            :placeholder="t('guest.phonePlaceholder')"
          />
        </label>

        <div class="field">
          <span class="label">{{ t('guest.birthday') }}</span>
          <div class="birthday-row">
            <select v-model="form.birthdayMonth">
              <option value="">{{ t('guest.month') }}</option>
              <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
            </select>
            <select v-model="form.birthdayDay">
              <option value="">{{ t('guest.day') }}</option>
              <option v-for="dd in days" :key="dd" :value="dd">{{ dd }}</option>
            </select>
          </div>
        </div>

        <label v-if="mode === 'pin'" class="field">
          <span class="label">{{ t('guest.pin') }}</span>
          <input
            v-model="form.pin"
            type="text"
            inputmode="numeric"
            autocomplete="off"
            maxlength="6"
            :placeholder="t('guest.pinPlaceholder')"
            @input="form.pin = form.pin.replace(/\D/g, '').slice(0, 6)"
          />
        </label>

        <div v-if="errorMsg" class="notice notice-error">{{ errorMsg }}</div>

        <button type="submit" class="btn-primary" :disabled="!canSubmit">
          {{ submitting ? t('guest.submitting') : mode === 'pin' ? t('guest.pinRecoverSubmit') : t('guest.loginSubmit') }}
        </button>
        <p class="readonly-note">
          {{ mode === 'pin' ? t('guest.pinRecoverNote') : t('guest.loginReadonlyNote') }}
        </p>
      </form>
    </template>
  </div>
</template>

<style scoped>
.card {
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 28px 24px 24px;
  margin-top: 24px;
}

h1 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px;
}

.lead {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 20px;
}

.mode-toggle {
  display: flex;
  gap: 8px;
  margin: 14px 0 12px;
}

.mode-toggle button {
  flex: 1;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 8px 12px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

.mode-toggle button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.label {
  font-size: 12.5px;
  color: var(--text-secondary);
  font-weight: 600;
}

input[type='tel'],
input[type='text'],
select {
  width: 100%;
  height: 44px;
  padding: 0 12px;
  font-size: 15px;
  color: var(--text-primary);
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
  box-sizing: border-box;
}

input:focus,
select:focus {
  border-color: var(--accent);
}

.birthday-row {
  display: flex;
  gap: 10px;
}

.btn-primary {
  height: 46px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.readonly-note {
  font-size: 11.5px;
  color: var(--text-tertiary);
  text-align: center;
  line-height: 1.5;
  margin: 0;
}

.picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

.picker-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 52px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-alt);
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.picker-logo {
  width: 36px;
  height: 36px;
  object-fit: contain;
  border-radius: 6px;
  flex-shrink: 0;
}

.picker-item:disabled {
  opacity: 0.5;
}

.text-btn {
  border: none;
  background: transparent;
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
}

.notice {
  font-size: 12.5px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  line-height: 1.5;
}

.notice-error {
  background: var(--danger-light);
  color: var(--danger);
}

.notice-info {
  background: var(--accent-light);
  color: var(--text-secondary);
  margin-bottom: 12px;
}
</style>
