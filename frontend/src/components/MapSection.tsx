import { CircleMarker, MapContainer, Polyline, TileLayer } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet'
import type { Coordinates, Place } from '../types'
import { t, type Lang } from '../i18n'
import { formatKm } from '../lib/format'

interface Props {
  campus: Coordinates
  city: Place | null
  distanceKm: number | null
  lang: Lang
}

/** The map card: desaturated OSM tiles, a terracotta campus dot, a black city-centre dot and a
 *  thin line between them; a legend above and the distance caption below. */
export default function MapSection({ campus, city, distanceKm, lang }: Props) {
  const campusPoint: LatLngExpression = [campus.lat, campus.lon]
  const cityPoint: LatLngExpression | null = city?.coords ? [city.coords.lat, city.coords.lon] : null
  const bounds: LatLngBoundsExpression | undefined = cityPoint ? [campusPoint, cityPoint] : undefined
  const km = distanceKm != null ? formatKm(distanceKm, lang) : null
  return (
    <section aria-label={t(lang, 'map_aria')} className="mt-16 md:mt-20">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-5">
        <div>
          <p className="eyebrow m-0">{t(lang, 'map_title')}</p>
          <h2 className="font-serif text-[26px] md:text-[32px] leading-[1.15] mt-2 m-0">
            {km ? t(lang, 'masthead_distance', { km }) : city?.name ?? ''}
          </h2>
        </div>
        <ul className="m-0 p-0 list-none flex items-center gap-5 text-[13px] text-ink-2">
          <li className="inline-flex items-center gap-2">
            <span className="w-[10px] h-[10px] rounded-full bg-accent" aria-hidden="true" />
            {t(lang, 'map_legend_campus')}
          </li>
          {cityPoint && (
            <li className="inline-flex items-center gap-2">
              <span className="w-[10px] h-[10px] rounded-full bg-ink" aria-hidden="true" />
              {t(lang, 'map_legend_center')}
            </li>
          )}
        </ul>
      </div>
      <div className="card overflow-hidden rounded-xl">
        <MapContainer
          className="map"
          bounds={bounds}
          boundsOptions={{ padding: [56, 56] }}
          center={bounds ? undefined : campusPoint}
          zoom={bounds ? undefined : 14}
          scrollWheelZoom={false}
          zoomControl={false}
          attributionControl
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
          />
          {cityPoint && (
            <>
              <Polyline
                positions={[campusPoint, cityPoint]}
                pathOptions={{ color: '#17140f', weight: 1.5, dashArray: '4 6' }}
              />
              <CircleMarker
                center={cityPoint}
                radius={7}
                pathOptions={{ color: '#ffffff', fillColor: '#17140f', fillOpacity: 1, weight: 2 }}
              />
            </>
          )}
          <CircleMarker
            center={campusPoint}
            radius={9}
            pathOptions={{ color: '#ffffff', fillColor: '#a4412f', fillOpacity: 1, weight: 2.5 }}
          />
        </MapContainer>
      </div>
      <p className="mt-3 text-[13px] text-ink-3 max-w-[70ch] m-0">
        {t(lang, 'map_caption', { km: km ?? '—' })}
      </p>
    </section>
  )
}
