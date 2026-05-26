'use client'

import {Button} from "@/shared/ui/button"
import {CtgCombinedPanel} from "@/features/ctg/ui/ctg-combined-panel"
import {Square} from "lucide-react"
import {pluck} from 'ramda'
import * as React from "react"
import {useEffect, useRef} from "react"
import {
    type AnnotationIntervals,
    connectStream,
    ensureIntervals,
    FHR_BACKGROUND_COLORS,
    FHR_LINE_COLORS,
    type Interval,
    mergeMomentsByTime,
    type StreamMessage,
    TOCO_BACKGROUND_COLORS,
    TOCO_LINE_COLORS
} from "@/features/ctg/lib/streaming"
import {
    getListMonitorsApiMonitorsGetQueryKey,
    useGetMonitorInfoApiMonitorsMonitorIdGet, useGetMonitorReportApiMonitorsMonitorIdReportGet,
    useStopMonitorApiMonitorsMonitorIdStopPost
} from "@/entities/generated/endpoints/ктг-мониторинг-api-v10-0-1-гц";
import {notEmpty} from "@/shared/lib/notEmpty";
import {toast} from "sonner";
import {useRouter} from "next/navigation";
import {useQueryClient} from "@tanstack/react-query";
import {Textarea} from "@/shared/ui/textarea"
import { Label } from "@/shared/ui/label"

export default function StartProcessPage() {
    const [data, setData] = React.useState<{ index: number; heart_beat: number; pussy_power: number }[]>([])
    const start = React.useRef(new Date())
    const router = useRouter();
    const sampleMs = 1000
    const [badge, setBadge] = React.useState<{ text: string; type: "normal" | "chronic" | "acute" }[]>([])
    const [running, setRunning] = React.useState(false)
    const [elapsedMs, setElapsedMs] = React.useState(0)
    const elapsedRef = React.useRef(0)
    const timerRef = React.useRef<NodeJS.Timeout | null>(null)
    const streamRef = React.useRef<{ abort: () => void } | null>(null)
    const runningRef = React.useRef(true)
    const originSecRef = React.useRef<number | null>(null)
    const [bandsHeart, setBandsHeart] = React.useState<{ start: number; end: number; color: string }[]>([])
    const [bandsToco, setBandsToco] = React.useState<{ start: number; end: number; color: string }[]>([])
    const [eventBands, setEventBands] = React.useState<{ start: number; end: number; color: string }[]>([])
    const [tocoEventBands, setTocoEventBands] = React.useState<{ start: number; end: number; color: string }[]>([])
    const id = typeof window !== 'undefined' ? sessionStorage.getItem('ktg_monitor_id') : ''
    const getMonitorInfo = useGetMonitorInfoApiMonitorsMonitorIdGet(id || '');

    useEffect(() => {
        if (notEmpty(getMonitorInfo.data?.is_running)) setRunning(getMonitorInfo.data?.is_running);
    }, [getMonitorInfo.data?.is_running])

    const showedToastSuccessRef = useRef(false);

    React.useEffect(() => {
        if (!id) return

        const connect = () => connectStream(id, (msg: StreamMessage) => {
            if (msg.kind === 'moments_batch') {
                setData(prev => mergeMomentsByTime(prev as any, msg, originSecRef as any, sampleMs))
                const warns = (msg as any)?.warnings
                if (Array.isArray(warns) && warns.length > 0) {
                    setBadge(warns.map(el => ({text: el, type: 'acute'})))
                }
            } else if (msg.kind === 'session_complete') {
                if (!showedToastSuccessRef.current && running) {
                    toast.success((msg as any)?.message || 'Обработка данных завершена')
                    setRunning(() => false);
                    showedToastSuccessRef.current = true;
                }
            } else if (msg.kind === 'annotation') {
                // Маппинг бейджа по статусу ЧСС и раскраска фоновых полос
                const ann = msg as AnnotationIntervals
                // приоритет: тяжелая тахи/бради -> acute, умеренная -> chronic, иначе normal
                const fhrIntervals = ensureIntervals(ann.fhr_line_status)
                const last = fhrIntervals.at(-1)
                if (last) {
                    let type: "normal" | "chronic" | "acute" = 'normal'
                    if (last.color_id === 2 || last.color_id === 0) type = 'acute'
                    else if (last.color_id === 1 || last.color_id === -1) type = 'chronic'
                    else type = 'normal'
                    const label = ann?.warnings || []
                    if (label) {
                        setBadge(label.map(el => ({text: el, type})))
                    }

                }
                // перекраска участков графиков
                const toBands = (arr: Interval[] | undefined, colors: Record<number, string | null>) => (arr ?? []).map(i => ({
                    start: Math.round(i.start / (sampleMs / 1000)),
                    end: Math.round(i.end / (sampleMs / 1000)),
                    color: String(colors[i.color_id] ?? '#000000')
                }))
                setBandsHeart(toBands(fhrIntervals, FHR_LINE_COLORS as any))
                const tocoIntervals = ensureIntervals(ann.toco_line_status)
                setBandsToco(toBands(tocoIntervals, TOCO_LINE_COLORS as any))
                const ev = ensureIntervals(ann.fhr_event_status)
                const evColor = (id: number) => id === 1 ? (FHR_BACKGROUND_COLORS[1] || '#F5C2C7') : id === -1 ? (FHR_BACKGROUND_COLORS[-1] || '#AED6F1') : 'transparent'
                setEventBands((ev ?? []).map(i => ({
                    start: Math.round(i.start / (sampleMs / 1000)),
                    end: Math.round(i.end / (sampleMs / 1000)),
                    color: evColor(i.color_id)
                })))

                // TOCO патологии как фоновые зоны
                const tachy = ensureIntervals(ann.toco_tachysystole)
                const hyper = ensureIntervals(ann.toco_hypertonus)
                const tetan = ensureIntervals(ann.toco_tetanic)
                const mapEv = (arr: Interval[] | undefined, color: string) => (arr ?? []).filter(i => i.color_id === 1).map(i => ({
                    start: Math.round(i.start / (sampleMs / 1000)),
                    end: Math.round(i.end / (sampleMs / 1000)),
                    color
                }))
                setTocoEventBands([
                    ...mapEv(tachy, TOCO_BACKGROUND_COLORS.tachysystole),
                    ...mapEv(hyper, TOCO_BACKGROUND_COLORS.hypertonus),
                    ...mapEv(tetan, TOCO_BACKGROUND_COLORS.tetanic),
                ])
            }
        }, undefined, {throttleMs: 120})
        const connP = connect()
        connP.then(c => {
            streamRef.current = c
        })

        timerRef.current = setInterval(() => {
            if (runningRef.current) {
                elapsedRef.current += 1000
                setElapsedMs(elapsed => elapsed + 1000)
            }
        }, 1000)

        return () => {
            connP.then(c => c.abort());
            showedToastSuccessRef.current = false;
            if (timerRef.current) clearInterval(timerRef.current);
        }
    }, [getMonitorInfo?.data, running])

    const stopMutation = useStopMonitorApiMonitorsMonitorIdStopPost();
    const queryClient = useQueryClient();

    const toggleRunning = async () => {
        if (!notEmpty(id)) {
            toast.error('Не найден id монитора')
            return;
        }

        if (running) {
            stopMutation.mutate({
                monitorId: id
            }, {
                onSuccess: async () => {
                    toast.success('Монитор успешно остановлен')
                    await queryClient.invalidateQueries({queryKey: getListMonitorsApiMonitorsGetQueryKey()});
                    router.push('/')
                },
                onError: (err) => {
                    toast.error(`Ошибка: ${err?.response?.data?.detail?.join(',')}`)
                }
            })
        }

        await queryClient.invalidateQueries({queryKey: getListMonitorsApiMonitorsGetQueryKey()});
    }

    const fmt = (ms: number) => {
        const s = Math.floor(ms / 1000)
        const mm = String(Math.floor(s / 60)).padStart(2, '0')
        const ss = String(s % 60).padStart(2, '0')
        return `${mm} мин. ${ss} сек.`
    }

    const getReportQuery = useGetMonitorReportApiMonitorsMonitorIdReportGet(id || '', {
        query: {
            enabled: !running
        }
    });


    return (
        <main className="p-4 md:p-6 lg:p-8">
            <div className="mb-4 text-sm text-muted-foreground flex items-center gap-2 flex-wrap">
                <div className="text-base text-foreground font-medium">Активный
                    монитор: {typeof window !== 'undefined' ? sessionStorage.getItem('ktg_monitor_id') : ''}</div>
            </div>

            <div className="grid grid-cols-1 gap-3">
                <CtgCombinedPanel name={'ЧСС'} data={data} lineKey="heart_beat" color="#22c55e"
                                  value={Math.round(data.at(-1)?.heart_beat ?? 0)} valueTitle="ЧСС • FHR1"
                                  status={'normal'}
                                  badgeText={pluck('text', badge)} startTime={start.current} sampleMs={sampleMs}
                                  yDomain={[60, 230]} bands={[]} eventBands={eventBands}
                                  thresholdsY={[100, 120, 160, 180]} animate={false} useD3 d3LineSegments={bandsHeart}
                                  legendItems={[
                                      {label: 'Линия: тяж. бради (<100)', color: FHR_LINE_COLORS[-2]},
                                      {label: 'Линия: бради (<120)', color: FHR_LINE_COLORS[-1]},
                                      {label: 'Линия: норма (120-160)', color: FHR_LINE_COLORS[0]},
                                      {label: 'Линия: тахи (>160)', color: FHR_LINE_COLORS[1]},
                                      {label: 'Линия: тяж. тахи (>180)', color: FHR_LINE_COLORS[2]},
                                      {label: 'Фон: децелерация', color: FHR_BACKGROUND_COLORS[-1] as any, kind: 'bg'},
                                      {label: 'Фон: акселерация', color: FHR_BACKGROUND_COLORS[1] as any, kind: 'bg'},
                                  ]}
                />
                <CtgCombinedPanel name={'Сократительная активность матки'} data={data} lineKey="pussy_power"
                                  color="#22c55e" value={Math.round(data.at(-1)?.pussy_power ?? 0)}
                                  valueTitle="Сократительная активность матки • TOCO" startTime={start.current}
                                  sampleMs={sampleMs} yDomain={[0, 130]} bands={[]} eventBands={tocoEventBands}
                                  thresholdsY={[0, 100]} animate={false} useD3 d3LineSegments={bandsToco}
                                  legendItems={[
                                      {label: 'Линия: низкая интенсивность', color: TOCO_LINE_COLORS[0]},
                                      {label: 'Линия: средняя интенсивность', color: TOCO_LINE_COLORS[1]},
                                      {label: 'Линия: высокая интенсивность', color: TOCO_LINE_COLORS[2]},
                                      {
                                          label: 'Фон: тахисистолия',
                                          color: TOCO_BACKGROUND_COLORS.tachysystole,
                                          kind: 'bg'
                                      },
                                      {label: 'Фон: гипертонус', color: TOCO_BACKGROUND_COLORS.hypertonus, kind: 'bg'},
                                      {label: 'Фон: тетания', color: TOCO_BACKGROUND_COLORS.tetanic, kind: 'bg'},
                                  ]}
                />
            </div>

            {!running && <div className={'mt-4 space-y-4'}>
                <Label htmlFor="message">Сформированный отчет:</Label>
                <Textarea id={'message'} className={'h-[300px]'} value={getReportQuery.data?.text_report}/>
                <div>
                    <Button variant={'outline'} className={'rounded-xl'} onClick={() => {
                        try {
                            const text = getReportQuery.data?.text_report || 'Отчет недоступен'
                            const monitorId = typeof window !== 'undefined' ? (sessionStorage.getItem('ktg_monitor_id') || '') : ''
                            const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
                            const url = URL.createObjectURL(blob)
                            const a = document.createElement('a')
                            a.href = url
                            a.download = `ctg_report_${monitorId || 'session'}.txt`
                            document.body.appendChild(a)
                            a.click()
                            a.remove()
                            URL.revokeObjectURL(url)
                        } catch {}
                    }}>Скачать отчет (.txt)</Button>
                </div>
            </div>}

            <ProcessToolbar running={running} onToggle={toggleRunning} elapsed={fmt(elapsedMs)}/>
        </main>
    )
}

function ProcessToolbar({running, onToggle, elapsed}: { running: boolean; onToggle: () => void; elapsed: string }) {
    return (
        <div className="sticky bottom-3 left-0 right-0 mt-4">
            <div className="mx-auto max-w-screen-2xl flex items-center gap-3 px-2">
                {running && <><Button variant={'destructive'} className="rounded-xl gap-2" onClick={onToggle}>
                    <Square className="size-4"/> Завершить
                </Button>
                    <div className="text-sm">{elapsed}</div>
                </>}
            </div>
        </div>
    )
}


