// Ambient globals shared by the Expo bundle and the Node verification harness.
//
// `__DEV__` is injected by Metro/React Native at build time but is *not* declared by any shipped
// type definition (checked against react-native 0.86 and expo 57), and it does not exist when the
// same modules are imported from Node — hence the guarded access in src/utils/logger.ts.

declare const __DEV__: boolean;
