"use client"

import {Button} from "@/shared/ui/button"
import {Card, CardContent} from "@/shared/ui/card"
import {Modal} from "@/shared/ui/modal"
import {CtgCombinedPanel} from "@/features/ctg/ui/ctg-combined-panel"
import {
  FHR_BACKGROUND_COLORS,
  FHR_LINE_COLORS,
  getInstantByMonitorId,
  type Interval,
  TOCO_BACKGROUND_COLORS,
  TOCO_LINE_COLORS
} from "@/features/ctg/lib/streaming"
import {Pencil, X} from "lucide-react"
import * as React from "react"
import {useState} from "react"
import {Label} from "@/shared/ui/label";
import {Textarea} from "@/shared/ui/textarea";

type Props = { onClose: () => void; result?: any; monitorId?: string }

export function SummaryModal({onClose, result, monitorId}: Props) {
  const [payload, setPayload] = React.useState<any>(result ?? null)

  React.useEffect(() => {
    if (!payload && monitorId) {
      getInstantByMonitorId(monitorId).then(setPayload).catch(() => {})
    }
  }, [monitorId])

  const moments = (payload?.moments ?? []) as Array<{ time_s?: number; real_time?: string; fhr_bpm: number; uterus_data: number }>
  const data = moments.map((m, idx) => ({ index: idx, rt: m.real_time, heart_beat: m.fhr_bpm, pussy_power: m.uterus_data }))
  const ann = Array.isArray(payload?.annotations) ? payload.annotations?.[0] : (payload?.annotations ?? {})
  const warnings: string[] = Array.isArray(ann?.warnings) ? ann.warnings : []
  const toBandsColor = (arr?: Array<Interval>, colors?: Record<number, string | null>) => (Array.isArray(arr) ? arr : []).map(i => ({ start: i.start, end: i.end, color: String(colors?.[i.color_id] ?? 'transparent') }))
  const bandsHeart = toBandsColor(ann?.fhr_line_status as any, FHR_LINE_COLORS as any)
  const bandsToco = toBandsColor(ann?.toco_line_status as any, TOCO_LINE_COLORS as any)
  const eventBands = toBandsColor(ann?.fhr_event_status as any, FHR_BACKGROUND_COLORS as any)
  const tocoEvents = [
    ...toBandsColor(ann?.toco_tachysystole as any, { 1: TOCO_BACKGROUND_COLORS.tachysystole } as any),
    ...toBandsColor(ann?.toco_hypertonus as any, { 1: TOCO_BACKGROUND_COLORS.hypertonus } as any),
    ...toBandsColor(ann?.toco_tetanic as any, { 1: TOCO_BACKGROUND_COLORS.tetanic } as any),
  ]

  const [report, setReport] = useState(payload?.text_report || '');


  return (
    <Modal open onOpenChange={(v) => { if (!v) onClose() }}>
      <Card className="border-input">
        <CardContent className="p-4 md:p-6">
          <div className="flex items-start justify-between mb-3">
            <div className="text-sm text-muted-foreground">Итог мгновенной обработки</div>
            <Button size="icon" variant="outline" className="rounded-xl" aria-label="Close" onClick={onClose}>
              <X className="size-4"/>
            </Button>
          </div>

          <div className="flex items-center gap-2 mb-4">
            <div className="text-2xl font-semibold">Пациент</div>
            <Button size="icon" variant="outline" aria-label="Edit"><Pencil className="size-4"/></Button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-3 mb-3">
            <Card className="border-input">
              <CardContent className="p-4 md:p-6 space-y-2">
                <div className="text-base font-medium">Warnings</div>
                {warnings.length > 0 ? (
                  <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1">
                    {warnings.map((w, i) => (<li key={i}>{w}</li>))}
                  </ul>
                ) : <div className="text-muted-foreground text-sm">Нет предупреждений</div>}
              </CardContent>
            </Card>
          </div>

          <div className="mb-3">
            <div className="flex items-center justify-between mb-2">
            <div className="text-base font-semibold">ЧСС</div>
            </div>
            <CtgCombinedPanel name={'ЧСС'} disableDopInfo data={data as any} lineKey="heart_beat" color="#22c55e" sampleMs={1000} yDomain={[60,230]} bands={[]} eventBands={eventBands} thresholdsY={[100,120,160,180]} useD3 d3LineSegments={bandsHeart} legendItems={[
              { label: 'Линия: тяж. бради (<100)', color: FHR_LINE_COLORS[-2] },
              { label: 'Линия: бради (<120)', color: FHR_LINE_COLORS[-1] },
              { label: 'Линия: норма (120-160)', color: FHR_LINE_COLORS[0] },
              { label: 'Линия: тахи (>160)', color: FHR_LINE_COLORS[1] },
              { label: 'Линия: тяж. тахи (>180)', color: FHR_LINE_COLORS[2] },
              { label: 'Фон: децелерация', color: FHR_BACKGROUND_COLORS[-1] as any, kind: 'bg' },
              { label: 'Фон: акселерация', color: FHR_BACKGROUND_COLORS[1] as any, kind: 'bg' },

            ]} />
          </div>

          <div className="mb-3">
            <div className="flex items-center justify-between mb-2">
            <div className="text-base font-semibold">Сократительная активность матки</div>
            </div>
            <CtgCombinedPanel name={'Сократительная активность матки'} disableDopInfo data={data as any} lineKey="pussy_power" color="#22c55e" sampleMs={1000} yDomain={[0,120]} bands={[]} eventBands={tocoEvents} thresholdsY={[0,100]} useD3 d3LineSegments={bandsToco} legendItems={[
              { label: 'Линия: низкая интенсивность', color: TOCO_LINE_COLORS[0] },
              { label: 'Линия: средняя интенсивность', color: TOCO_LINE_COLORS[1] },
              { label: 'Линия: высокая интенсивность', color: TOCO_LINE_COLORS[2] },
              { label: 'Фон: тахисистолия', color: TOCO_BACKGROUND_COLORS.tachysystole, kind: 'bg' },
              { label: 'Фон: гипертонус', color: TOCO_BACKGROUND_COLORS.hypertonus, kind: 'bg' },
              { label: 'Фон: тетания', color: TOCO_BACKGROUND_COLORS.tetanic, kind: 'bg' },
            ]} />
          </div>

          <div className={'mt-4 space-y-4'}>
            <Label htmlFor="message">Сформированный отчет:</Label>
            <Textarea id={'message'} onChange={e => setReport(e.target.value)} className={'h-[300px]'} value={report}/>
            <div>
              <Button variant={'outline'} className={'rounded-xl'} onClick={() => {
                const text = report || 'Отчет недоступен'
                const blob = new Blob([text], {type: 'text/plain;charset=utf-8'})
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `ctg_report_${monitorId || 'session'}.txt`
                document.body.appendChild(a)
                a.click()
                a.remove()
                URL.revokeObjectURL(url)
              }}>Скачать отчет (.txt)</Button>
            </div>
          </div>

          <div className="flex items-center gap-3 mt-2">
            <Button variant="outline" className="rounded-xl">Скачать PDF</Button>
            <Button variant="outline" className="rounded-xl">Распечатать итог для медкарты</Button>
          </div>
        </CardContent>
      </Card>
    </Modal>
  )
}



