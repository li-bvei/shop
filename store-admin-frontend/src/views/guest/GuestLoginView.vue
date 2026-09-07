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

const orgName = (o: RecoveryOption) => {
  const chain = locale.value === 'ja' ? o.orgNameJa : o.orgNameZh
  const branch = locale.value === 'ja' ? o.branchNameJa : o.branchNameZh
  return [chain, branch].filter(Boolean).join(' ')
}

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
  <div class="login-view">
    <section class="g-intro">
      <p class="g-eyebrow">{{ t('guest.eyebrowRecover') }}</p>
      <h1 class="g-title">{{ t('guest.loginTitle') }}</h1>
      <p v-if="!pickerOptions" class="g-lead">
        {{ mode === 'pin' ? t('guest.pinRecoverLead') : t('guest.loginLead') }}
      </p>
    </section>

    <p v-if="cameFromExisting" class="g-notice is-info">{{ t('guest.existingHint') }}</p>

    <!-- merchant picker -->
    <template v-if="pickerOptions">
      <p class="g-lead pick-lead">{{ t('guest.pickCardLead') }}</p>
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
      <button type="button" class="g-link" @click="pickerOptions = null">{{ t('common.back') }}</button>
    </template>

    <template v-else>
      <div class="g-modeswitch">
        <button type="button" :class="{ active: mode === 'pin' }" @click="switchMode('pin')">
          {{ t('guest.modePin') }}
        </button>
        <button type="button" :class="{ active: mode === 'view' }" @click="switchMode('view')">
          {{ t('guest.modeView') }}
        </button>
      </div>

      <form class="g-form" @submit.prevent="submit">
        <label class="g-field">
          <span class="g-field-label">{{ t('guest.phone') }}</span>
          <input
            v-model="form.phone"
            class="g-input"
            type="tel"
            inputmode="numeric"
            autocomplete="tel"
            :placeholder="t('guest.phonePlaceholder')"
          />
        </label>

        <div class="g-field">
          <span class="g-field-label">{{ t('guest.birthday') }}</span>
          <div class="g-date-row">
            <select v-model="form.birthdayMonth" class="g-select">
              <option value="">{{ t('guest.month') }}</option>
              <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
            </select>
            <span>{{ t('guest.month') }}</span>
            <select v-model="form.birthdayDay" class="g-select">
              <option value="">{{ t('guest.day') }}</option>
              <option v-for="dd in days" :key="dd" :value="dd">{{ dd }}</option>
            </select>
            <span>{{ t('guest.day') }}</span>
          </div>
        </div>

        <label v-if="mode === 'pin'" class="g-field">
          <span class="g-field-label">{{ t('guest.pin') }}</span>
          <input
            v-model="form.pin"
            class="g-input"
            type="text"
            inputmode="numeric"
            autocomplete="off"
            maxlength="6"
            :placeholder="t('guest.pinPlaceholder')"
            @input="form.pin = form.pin.replace(/\D/g, '').slice(0, 6)"
          />
        </label>

        <div class="g-privacy">{{ mode === 'pin' ? t('guest.pinRecoverNote') : t('guest.loginReadonlyNote') }}</div>

        <div v-if="errorMsg" class="g-notice is-error">{{ errorMsg }}</div>

        <button type="submit" class="g-btn-primary" :disabled="!canSubmit">
          {{ submitting ? t('guest.submitting') : mode === 'pin' ? t('guest.pinRecoverSubmit') : t('guest.loginSubmit') }}
        </button>
      </form>
    </template>
  </div>
</template>

<style scoped>
.login-view {
  padding-top: 4px;
}

.pick-lead {
  margin-bottom: 14px;
}

.g-privacy {
  display: flex;
  gap: 8px;
  padding: 13px;
  border-radius: 10px;
  background: var(--guest-soft);
  color: var(--guest-muted);
  font-size: 11px;
  line-height: 1.55;
}

.picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.picker-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 56px;
  padding: 10px 15px;
  border: 1px solid var(--guest-field-border);
  border-radius: 14px;
  background: #fff;
  color: var(--guest-ink);
  font-family: inherit;
  font-size: 15px;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

.picker-item:active {
  background: var(--guest-soft);
}

.picker-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.picker-logo {
  width: 36px;
  height: 36px;
  object-fit: contain;
  border-radius: 8px;
  flex-shrink: 0;
}
</style>
