"use client"

import * as React from "react"
// @ts-ignore - типы опциональны для быстрого внедрения
import * as d3 from "d3"
import {cn} from "@/shared/lib/css"

export type D3Band = { start: number; end: number; color: string; opacity?: number }

export type D3Point = { index: number; ts?: number; rt?: string; heart_beat: number; pussy_power: number }

type Props = {
  className?: string
  width?: number
  height?: number
  data: D3Point[]
  yDomain: [number, number]
  bands?: D3Band[]
  color?: string
  eventBands?: D3Band[]
  name?: string
  baselineWindowPoints?: number
  valueKey?: keyof D3Point
  lineSegments?: D3Band[]
  thresholdsY?: number[]
}

export function D3CTG({ className, width = 800, height = 230, data, yDomain, bands = [], color = "#22c55e", eventBands = [], name, baselineWindowPoints = 90, valueKey = 'heart_beat', lineSegments = [], thresholdsY = [] }: Props) {
  const ref = React.useRef<SVGSVGElement | null>(null)

  React.useEffect(() => {
    if (!ref.current) return
    const svg = d3.select(ref.current)
    svg.selectAll("*").remove()

    const margin = { top: 8, right: 8, bottom: 20, left: 28 }
    const innerW = width - margin.left - margin.right
    const innerH = height - margin.top - margin.bottom

    const g = svg
      .attr("viewBox", `0 0 ${width} ${height}`)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`)

    const showTime = data.some(d => typeof d.ts === 'number')
    const x = (showTime
      ? d3.scaleLinear().domain(d3.extent(data, (d: D3Point) => d.ts as number) as [number, number]).range([0, innerW])
      : d3.scaleLinear().domain(d3.extent(data, (d: D3Point) => d.index) as [number, number]).range([0, innerW]))
      .clamp(true)
    const y = d3.scaleLinear().domain(yDomain).range([innerH, 0]).clamp(true)

    // clip-path, чтобы всё рисовалось в пределах области графика
    const clipId = `clip-${Math.random().toString(36).slice(2)}`
    const defs = svg.append("defs")
    defs.append("clipPath").attr("id", clipId)
      .append("rect").attr("x", 0).attr("y", 0).attr("width", innerW).attr("height", innerH)

    // grid
    g.append("g").attr("class", "grid")
      .attr("transform", `translate(0,${innerH})`)
      .call((d3.axisBottom(x) as any).ticks(10).tickSize(-innerH).tickFormat(() => "" as any))
      .selectAll("line").attr("stroke", "currentColor").attr("stroke-opacity", 0.2)

    g.append("g").attr("class", "grid")
      .call((d3.axisLeft(y) as any).ticks(5).tickSize(-innerW).tickFormat(() => "" as any))
      .selectAll("line").attr("stroke", "currentColor").attr("stroke-opacity", 0.2)

    // bands (line statuses)
    const bandG = g.append("g").attr("clip-path", `url(#${clipId})`)
    bands.forEach(b => {
      bandG.append("rect")
        .attr("x", x(b.start))
        .attr("width", Math.max(1, x(b.end) - x(b.start)))
        .attr("y", 0)
        .attr("height", innerH)
        .attr("fill", b.color)
        .attr("fill-opacity", b.opacity ?? 0.18)
    })

    // event bands (accel/decel) on top with lighter opacity
    const evG = g.append("g").attr("clip-path", `url(#${clipId})`)
    eventBands.forEach(b => {
      evG.append("rect")
        .attr("x", x(b.start))
        .attr("width", Math.max(1, x(b.end) - x(b.start)))
        .attr("y", 0)
        .attr("height", innerH)
        .attr("fill", b.color)
        .attr("fill-opacity", b.opacity ?? 0.15)
    })

    const line = (d3.line() as any)
      .curve(d3.curveMonotoneX)
      .x((d: D3Point) => x(showTime ? (d.ts as number) : d.index))
      .y((d: D3Point) => y((d[valueKey] as unknown as number)))

    // optional thresholds
    if (Array.isArray(thresholdsY) && thresholdsY.length > 0) {
      const thrG = g.append("g")
      thresholdsY.forEach(val => {
        thrG.append("line")
          .attr("x1", 0)
          .attr("x2", innerW)
          .attr("y1", y(val))
          .attr("y2", y(val))
          .attr("stroke", "currentColor")
          .attr("stroke-dasharray", "4 4")
          .attr("stroke-opacity", 0.35)
      })
    }

    // area/line or segmented line by intervals
    if (!lineSegments || lineSegments.length === 0) {
      const area = (d3.area() as any)
        .curve(d3.curveMonotoneX)
        .x((d: D3Point) => x(showTime ? (d.ts as number) : d.index))
        .y0(innerH)
        .y1((d: D3Point) => y((d[valueKey] as unknown as number)))
      g.append("g").attr("clip-path", `url(#${clipId})`).append("path").datum(data).attr("d", area as any).attr("fill", color).attr("fill-opacity", 0.08)
      g.append("g").attr("clip-path", `url(#${clipId})`).append("path").datum(data).attr("d", line as any).attr("stroke", color).attr("stroke-width", 2).attr("fill", "none")
    } else {
      // draw segments in different colors
      const idxByX = (val: number) => {
        const arr = data
        let lo = 0, hi = arr.length - 1
        const getter = (d: D3Point) => (showTime ? (d.ts as number) : d.index)
        while (lo <= hi) {
          const mid = (lo + hi) >> 1
          const mv = getter(arr[mid])
          if (mv < val) lo = mid + 1
          else if (mv > val) hi = mid - 1
          else return mid
        }
        return Math.max(0, Math.min(arr.length - 1, lo))
      }
      for (const seg of lineSegments) {
        const i0 = idxByX(seg.start)
        const i1 = idxByX(seg.end)
        if (i1 <= i0) continue
        const slice = data.slice(i0, i1 + 1)
        g.append("g").attr("clip-path", `url(#${clipId})`).append("path").datum(slice).attr("d", line as any).attr("stroke", seg.color).attr("stroke-width", 2).attr("fill", "none")
      }
    }

    // // baseline (moving average)
    // if (baselineWindowPoints > 1) {
    //   const kernel = baselineWindowPoints
    //   const avg: D3Point[] = []
    //   let sum = 0
    //   const hb = data.map(d => d.heart_beat)
    //   for (let i = 0; i < hb.length; i++) {
    //     sum += hb[i]
    //     if (i >= kernel) sum -= hb[i - kernel]
    //     const val = i >= kernel - 1 ? sum / kernel : hb[i]
    //       avg.push({ index: data[i].index, ts: data[i].ts, heart_beat: val, pussy_power: 0 })
    //   }
    //   const baseLine = (d3.line() as any).curve(d3.curveMonotoneX).x((d: D3Point) => x(showTime ? (d.ts as number) : d.index)).y((d: D3Point) => y(d.heart_beat))
    //   g.append("path").datum(avg).attr("d", baseLine as any).attr("stroke", "#9ca3af").attr("stroke-dasharray", "4 4").attr("stroke-width", 1.5).attr("fill", "none").attr("opacity", 0.9)
    // }

    // axes without labels
    const fmtTime = (t: number) => {
      const mm = Math.floor(t / 60)
      const ss = Math.floor(t % 60)
      return `${mm}:${String(ss).padStart(2, '0')}`
    }
    const bottomAxis = (d3.axisBottom(x) as any).ticks(6)
      .tickFormat(showTime ? ((val: unknown) => fmtTime(Number(val))) : undefined)
    g.append("g").attr("transform", `translate(0,${innerH})`).call(bottomAxis).call((g: any) => g.selectAll("text").attr("opacity", 0.6))
    g.append("g").call((d3.axisLeft(y) as any).ticks(5)).call((g: any) => g.selectAll("text").attr("opacity", 0.6))

    if (name) {
      svg.append("text").attr("x", margin.left).attr("y", 14)
        .text(name)
        .attr("fill", "currentColor").attr("opacity", 0.8)
        .attr("font-size", 12)
    }

  // tooltip: линия наведения и значения в точке
  const overlay = g.append("rect")
    .attr("x", 0)
    .attr("y", 0)
    .attr("width", innerW)
    .attr("height", innerH)
    .attr("fill", "transparent")
    .style("cursor", "crosshair")

  const tip = g.append("g").style("display", "none")
  const tipLine = tip.append("line").attr("stroke", "#9ca3af").attr("stroke-width", 1).attr("y1", 0).attr("y2", innerH)
  const tipDot = tip.append("circle").attr("r", 3.5).attr("fill", color).attr("stroke", "#ffffff").attr("stroke-width", 1)
  const tipBox = tip.append("rect").attr("fill", "#111827").attr("opacity", 0.9).attr("rx", 6)
  const tipText = tip.append("text").attr("fill", "#e5e7eb").attr("font-size", 11)

  const accessorX = (d: D3Point) => (showTime ? (d.ts as number) : d.index)
  const pointLabelTime = (d: D3Point) => {
    if (d.rt) return d.rt
    if (showTime && typeof d.ts === 'number') return fmtTime(d.ts)
    return `#${d.index}`
  }
  const bisect = (d3 as any).bisector(accessorX).left

  const onMove = (event: any) => {
    const [mx] = (d3 as any).pointer(event)
    const xVal = (x as any).invert(mx)
    const i = Math.max(0, Math.min(data.length - 1, bisect(data, xVal)))
    const d = data[i]
    const cx = x(accessorX(d))
    const cy = y((d[valueKey] as unknown as number))
    tip.style("display", null)
    tip.attr("transform", `translate(${cx},0)`)
    tipLine.attr("x1", 0).attr("x2", 0)
    tipDot.attr("cx", 0).attr("cy", cy)
    const lines: string[] = [
      `${name ?? 'Series'}: ${Math.round(d[valueKey] as unknown as number)}`,
      `Время: ${pointLabelTime(d)}`
    ]
    tipText.selectAll("tspan").remove()
    lines.forEach((t, idx) => tipText.append("tspan").attr("x", 8).attr("y", 10 + idx * 14).text(t))
    const bbox = (tipText.node() as any).getBBox()
    const labelX = cx + bbox.width + 24 > innerW ? -bbox.width - 16 : 8
    const labelY = 8
    tipBox.attr("x", labelX - 6).attr("y", labelY - 8).attr("width", bbox.width + 12).attr("height", bbox.height + 12)
    tipText.attr("transform", `translate(${labelX},${labelY})`)
  }

  overlay.on("mousemove", onMove).on("mouseleave", () => tip.style("display", "none"))
  }, [data, yDomain, bands, color, width, height, valueKey, lineSegments, thresholdsY])

  return <svg ref={ref} className={cn("w-full", className)} />
}


