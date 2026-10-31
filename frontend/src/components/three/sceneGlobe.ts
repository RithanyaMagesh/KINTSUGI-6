// Photoreal Earth for the live 3D view: NASA Blue Marble day map, city lights
// on the night side, a sun-lit terminator, ocean glint from a water mask, a
// drifting cloud shell and a two-layer atmosphere. Textures are vendored in
// public/textures/ (from the MIT three-globe package; imagery is NASA public
// domain) — no CDN. Until they load, the procedural map passed in is shown,
// so the globe is never blank. Purely visual: nothing here feeds a number.
import * as THREE from "three";

/** Fixed world-space sun direction shared by the globe shader and the scene
 * lights, so the CubeSat models are lit from the same side as the day side. */
export const SUN_DIR = new THREE.Vector3(0.54, 0.19, -0.73).normalize();

const BASE = import.meta.env.BASE_URL ?? "/";

function load(loader: THREE.TextureLoader, name: string, srgb: boolean, onLoad: (t: THREE.Texture) => void): void {
  loader.load(`${BASE}textures/${name}`, (tex) => {
    tex.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    tex.anisotropy = 1;
    onLoad(tex);
  });
}

const EARTH_VERT = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vViewDirW;
  varying vec3 vPosO;
  varying vec3 vNormalO;
  void main() {
    vUv = uv;
    vPosO = position;
    vNormalO = normal;
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vViewDirW = normalize(cameraPosition - wp.xyz);
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const EARTH_FRAG = /* glsl */ `
  uniform sampler2D uDay;
  uniform sampler2D uNight;
  uniform sampler2D uWater;
  uniform vec3 uSun;
  uniform float uHasNight;
  uniform vec3 uAtmo;
  uniform sampler2D uTopo;
  uniform sampler2D uClouds;
  uniform float uCloudAmt;
  uniform float uCloudShift;
  uniform float uBump;
  uniform mat3 uObjToWorld;
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vViewDirW;
  varying vec3 vPosO;
  varying vec3 vNormalO;

  // Relief from the elevation map: central differences on the texture,
  // bent along the sphere's east/north tangents, so mountains catch the sun
  // and the globe reads as a solid body rather than a painted ball.
  vec3 reliefNormal(vec3 p, vec2 uv) {
    vec3 nn = normalize(p);
    vec3 e = normalize(vec3(p.z, 0.0, -p.x) + vec3(1e-5, 0.0, 0.0));
    vec3 north = cross(nn, e);
    vec2 d = vec2(1.0 / 2048.0, 1.0 / 1024.0);
    float hx = texture2D(uTopo, uv + vec2(d.x, 0.0)).r - texture2D(uTopo, uv - vec2(d.x, 0.0)).r;
    float hy = texture2D(uTopo, uv + vec2(0.0, d.y)).r - texture2D(uTopo, uv - vec2(0.0, d.y)).r;
    return normalize(nn - uBump * (hx * e + hy * north));
  }

  void main() {
    float water = texture2D(uWater, vUv).r;
    vec3 nO = reliefNormal(vPosO, vUv);
    vec3 n = normalize(uObjToWorld * nO);
    vec3 v = normalize(vViewDirW);
    float ndl = dot(n, uSun);
    float day = smoothstep(-0.12, 0.22, dot(normalize(vNormalW), uSun));
    vec3 dayCol = texture2D(uDay, vUv).rgb;
    vec3 nightRaw = texture2D(uNight, vUv).rgb;
    // Square the night map: its dim blue base drops to black, city lights stay.
    vec3 nightCol = nightRaw * nightRaw * vec3(1.0, 0.75, 0.42) * 4.0 * uHasNight;
    vec3 h = normalize(uSun + v);
    float spec = pow(max(dot(normalize(vNormalW), h), 0.0), 220.0) * water * 0.14 * day;
    vec3 lit = dayCol * (0.04 + 1.15 * max(ndl, 0.0)) + spec * vec3(1.0, 0.95, 0.85);
    // Clouds live on the surface shader (no separate transparent shell):
    // lit white by day, and they dim the city lights by night.
    float cloud = texture2D(uClouds, vUv + vec2(uCloudShift, 0.0)).r * uCloudAmt;
    float sunSmooth = max(dot(normalize(vNormalW), uSun), 0.0);
    lit = mix(lit, vec3(0.03 + 1.05 * sunSmooth), cloud * 0.85);
    nightCol *= 1.0 - cloud * 0.75;
    vec3 col = mix(nightCol + dayCol * 0.012, lit, day);
    // Limb haze: a thin bright rim on the sunlit edge only.
    float fres = pow(1.0 - max(dot(normalize(vNormalW), v), 0.0), 3.0);
    col += uAtmo * fres * (0.04 + 0.96 * smoothstep(-0.15, 0.5, dot(normalize(vNormalW), uSun))) * 1.1;
    gl_FragColor = vec4(col, 1.0);
    #include <colorspace_fragment>
  }
`;

const ATMO_VERT = /* glsl */ `
  varying vec3 vNormalW;
  varying vec3 vViewDirW;
  void main() {
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vViewDirW = normalize(cameraPosition - wp.xyz);
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const ATMO_FRAG = /* glsl */ `
  uniform vec3 uAtmo;
  uniform vec3 uSun;
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vViewDirW;
  void main() {
    vec3 n = normalize(vNormalW);
    float f = clamp(-dot(n, normalize(vViewDirW)) / 0.42, 0.0, 1.0);
    float glow = pow(f, 2.2);
    float lit = smoothstep(-0.5, 0.45, dot(n, uSun));
    gl_FragColor = vec4(uAtmo * (0.6 + 0.7 * lit), glow * (0.02 + 0.98 * lit));
  }
`;

export interface Globe {
  group: THREE.Group;
  /** Rotating surface (spin applied by the caller). */
  surface: THREE.Group;
  setAtmoColor(c: THREE.Color): void;
  setFallbackMap(t: THREE.Texture): void;
  update(dt: number, reducedMotion: boolean): void;
  dispose(): void;
}

export function buildGlobe(fallbackDay: THREE.Texture, atmo: THREE.Color): Globe {
  const group = new THREE.Group();
  const surface = new THREE.Group();
  group.add(surface);

  const black = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
  black.needsUpdate = true;

  const earthGeo = new THREE.SphereGeometry(1, 128, 96);
  const earthMat = new THREE.ShaderMaterial({
    uniforms: {
      uDay: { value: fallbackDay },
      uNight: { value: black },
      uWater: { value: black },
      uSun: { value: SUN_DIR.clone() },
      uHasNight: { value: 0 },
      uAtmo: { value: atmo.clone() },
      uTopo: { value: black },
      uClouds: { value: black },
      uCloudAmt: { value: 0 },
      uCloudShift: { value: 0 },
      uBump: { value: 0 },
      uObjToWorld: { value: new THREE.Matrix3() },
    },
    vertexShader: EARTH_VERT,
    fragmentShader: EARTH_FRAG,
  });
  surface.add(new THREE.Mesh(earthGeo, earthMat));

  const atmoGeo = new THREE.SphereGeometry(1.1, 96, 72);
  const atmoMat = new THREE.ShaderMaterial({
    uniforms: { uAtmo: { value: atmo.clone() }, uSun: { value: SUN_DIR.clone() } },
    vertexShader: ATMO_VERT,
    fragmentShader: ATMO_FRAG,
    side: THREE.BackSide,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  group.add(new THREE.Mesh(atmoGeo, atmoMat));

  const loaded: THREE.Texture[] = [];
  let usingFallback = true;
  const loader = new THREE.TextureLoader();
  load(loader, "earth-day.jpg", true, (t) => {
    loaded.push(t);
    usingFallback = false;
    earthMat.uniforms.uDay.value = t;
  });
  load(loader, "earth-night.jpg", true, (t) => {
    loaded.push(t);
    earthMat.uniforms.uNight.value = t;
    earthMat.uniforms.uHasNight.value = 1;
  });
  load(loader, "earth-water.jpg", false, (t) => {
    loaded.push(t);
    earthMat.uniforms.uWater.value = t;
  });
  load(loader, "earth-topology.jpg", false, (t) => {
    loaded.push(t);
    earthMat.uniforms.uTopo.value = t;
    earthMat.uniforms.uBump.value = 2.2; // exaggerated relief strength
  });
  load(loader, "earth-clouds.jpg", false, (t) => {
    loaded.push(t);
    t.wrapS = THREE.RepeatWrapping;
    earthMat.uniforms.uClouds.value = t;
    earthMat.uniforms.uCloudAmt.value = 1;
  });

  let cloudSpin = 0;
  return {
    group,
    surface,
    setAtmoColor(c) {
      earthMat.uniforms.uAtmo.value = c.clone();
      atmoMat.uniforms.uAtmo.value = c.clone();
    },
    setFallbackMap(t) {
      if (usingFallback) earthMat.uniforms.uDay.value = t;
    },
    update(dt, reducedMotion) {
      surface.updateMatrixWorld();
      (earthMat.uniforms.uObjToWorld.value as THREE.Matrix3).getNormalMatrix(surface.matrixWorld);
      if (reducedMotion) return;
      cloudSpin += dt * 0.0008;
      earthMat.uniforms.uCloudShift.value = cloudSpin % 1;
    },
    dispose() {
      for (const t of loaded) t.dispose();
      black.dispose();
      earthGeo.dispose();
      earthMat.dispose();
      atmoGeo.dispose();
      atmoMat.dispose();
    },
  };
}
