// spin-wheel 5.0.2 ships plain JS without type declarations; this covers only
// the surface WheelOfFortune.vue uses (pinned exactly in package.json).
declare module 'spin-wheel' {
  export interface WheelItem {
    label?: string
    backgroundColor?: string
    labelColor?: string
    weight?: number
  }
  export interface WheelEventPayload {
    type: string
    currentIndex: number
    rotation?: number
  }
  export interface WheelProps {
    items?: WheelItem[]
    radius?: number
    rotation?: number
    pointerAngle?: number
    isInteractive?: boolean
    borderWidth?: number
    borderColor?: string
    lineWidth?: number
    lineColor?: string
    itemLabelRadius?: number
    itemLabelRadiusMax?: number
    itemLabelRotation?: number
    itemLabelAlign?: 'left' | 'center' | 'right'
    itemLabelFont?: string
    itemLabelFontSizeMax?: number
    itemLabelBaselineOffset?: number
    onCurrentIndexChange?: (event: WheelEventPayload) => void
    onRest?: (event: WheelEventPayload) => void
    onSpin?: (event: WheelEventPayload) => void
  }
  export class Wheel {
    constructor(container: Element, props?: WheelProps)
    items: WheelItem[]
    readonly rotation: number
    spinToItem(
      itemIndex: number, duration?: number, spinToCenter?: boolean,
      numberOfRevolutions?: number, direction?: number, easingFunction?: ((n: number) => number) | null,
    ): void
    stop(): void
    resize(): void
    remove(): void
  }
}
