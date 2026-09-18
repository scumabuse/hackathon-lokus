/** MapCard — react-leaflet map with university and city coords */
import { useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Coordinates, Place } from '../types'
import type { Lang } from '../i18n'
import { UI } from '../i18n'

// Fix default icons for Vite
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
})

interface Props {
  uniCoords?: Coordinates
  city?: Place
  distanceKm?: number
  lang: Lang
}

function BoundsFitter({ uniCoords, cityCoords }: { uniCoords: Coordinates, cityCoords: Coordinates }) {
  const map = useMap()
  useEffect(() => {
    map.fitBounds([
      [uniCoords.lat, uniCoords.lon],
      [cityCoords.lat, cityCoords.lon]
    ], { padding: [50, 50] })
  }, [map, uniCoords, cityCoords])
  return null
}

export default function MapCard({ uniCoords, city, distanceKm, lang }: Props) {
  if (!uniCoords) return null

  const t = (k: string) => UI[k]?.[lang] ?? k
  const cityCoords = city?.coords

  return (
    <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm my-8">
      <div className="h-[300px] w-full relative z-0">
        <MapContainer 
          center={[uniCoords.lat, uniCoords.lon]} 
          zoom={cityCoords ? 11 : 13} 
          scrollWheelZoom={false}
          className="h-full w-full"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          
          <Marker position={[uniCoords.lat, uniCoords.lon]}>
             <Tooltip permanent direction="top" offset={[0, -20]} className="font-semibold shadow-sm">
                Кампус
             </Tooltip>
          </Marker>

          {cityCoords && (
            <>
              <Marker position={[cityCoords.lat, cityCoords.lon]}>
                <Tooltip permanent direction="bottom" offset={[0, 20]} className="font-semibold shadow-sm text-slate-500">
                  {city.name}
                </Tooltip>
              </Marker>
              
              <Polyline 
                positions={[
                  [uniCoords.lat, uniCoords.lon],
                  [cityCoords.lat, cityCoords.lon]
                ]} 
                color="#3b82f6" 
                weight={3} 
                dashArray="5, 10" 
              />
              
              <BoundsFitter uniCoords={uniCoords} cityCoords={cityCoords} />
            </>
          )}
        </MapContainer>
      </div>
      
      {distanceKm != null && (
        <div className="p-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between">
          <span className="font-medium text-slate-700">Расстояние до центра</span>
          <span className="bg-white px-3 py-1 rounded-full text-sm font-semibold text-blue-600 border border-slate-200">
            {distanceKm} {t('distanceToCity')}
          </span>
        </div>
      )}
    </div>
  )
}
