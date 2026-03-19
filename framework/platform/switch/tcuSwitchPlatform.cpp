/*
 * VK-GL-CTS Nintendo Switch Platform
 *
 * Platform layer for running dEQP conformance tests on Nintendo Switch
 * using SwitchGLES (OpenGL ES 2.0 + EGL 1.4 over deko3d).
 */

#include "tcuSwitchPlatform.hpp"

#include "egluNativeDisplay.hpp"
#include "egluNativeWindow.hpp"
#include "egluGLContextFactory.hpp"
#include "eglwLibrary.hpp"
#include "eglwEnums.hpp"

#include <switch.h>

namespace tcu
{
namespace nx
{

// --- Native Window ---

class SwitchNativeWindow : public eglu::NativeWindow
{
public:
	SwitchNativeWindow(const eglu::WindowParams& params)
		: eglu::NativeWindow(static_cast<eglu::NativeWindow::Capability>(
		                     eglu::NativeWindow::CAPABILITY_CREATE_SURFACE_LEGACY |
		                     eglu::NativeWindow::CAPABILITY_GET_SURFACE_SIZE))
		, m_width(params.width == eglu::WindowParams::SIZE_DONT_CARE ? 1280 : params.width)
		, m_height(params.height == eglu::WindowParams::SIZE_DONT_CARE ? 720 : params.height)
	{
		m_nativeWindow = nwindowGetDefault();
	}

	eglw::EGLNativeWindowType getLegacyNative(void)
	{
		return (eglw::EGLNativeWindowType)m_nativeWindow;
	}

	tcu::IVec2 getSurfaceSize(void) const
	{
		return tcu::IVec2(m_width, m_height);
	}

private:
	NWindow*	m_nativeWindow;
	int			m_width;
	int			m_height;
};

// --- Native Window Factory ---

class SwitchNativeWindowFactory : public eglu::NativeWindowFactory
{
public:
	SwitchNativeWindowFactory(void)
		: eglu::NativeWindowFactory("switch", "Nintendo Switch Window",
		                            static_cast<eglu::NativeWindow::Capability>(
		                            eglu::NativeWindow::CAPABILITY_CREATE_SURFACE_LEGACY |
		                            eglu::NativeWindow::CAPABILITY_GET_SURFACE_SIZE))
	{
	}

	eglu::NativeWindow* createWindow(eglu::NativeDisplay*, const eglu::WindowParams& params) const
	{
		return new SwitchNativeWindow(params);
	}
};

// --- Native Display ---

class SwitchNativeDisplay : public eglu::NativeDisplay
{
public:
	SwitchNativeDisplay(void)
		: eglu::NativeDisplay(CAPABILITY_GET_DISPLAY_LEGACY)
		, m_library(nullptr)
	{
		// Use DefaultLibrary with nullptr = no dlopen, uses static link + eglGetProcAddress
		m_library = new eglw::DefaultLibrary(nullptr);
	}

	~SwitchNativeDisplay(void)
	{
		delete m_library;
	}

	const eglw::Library& getLibrary(void) const
	{
		return *m_library;
	}

	eglw::EGLNativeDisplayType getLegacyNative(void)
	{
		return EGL_DEFAULT_DISPLAY;
	}

private:
	eglw::DefaultLibrary*	m_library;
};

// --- Native Display Factory ---

class SwitchNativeDisplayFactory : public eglu::NativeDisplayFactory
{
public:
	SwitchNativeDisplayFactory(void)
		: eglu::NativeDisplayFactory("switch", "Nintendo Switch Display",
		                             eglu::NativeDisplay::CAPABILITY_GET_DISPLAY_LEGACY)
	{
		m_nativeWindowRegistry.registerFactory(new SwitchNativeWindowFactory());
	}

	eglu::NativeDisplay* createDisplay(const eglw::EGLAttrib*) const
	{
		return new SwitchNativeDisplay();
	}
};

// --- Platform ---

Platform::Platform(void)
{
	m_nativeDisplayFactoryRegistry.registerFactory(new SwitchNativeDisplayFactory());
	m_contextFactoryRegistry.registerFactory(
		new eglu::GLContextFactory(m_nativeDisplayFactoryRegistry));
}

Platform::~Platform(void)
{
}

bool Platform::processEvents(void)
{
	/* appletMainLoop() returns false when the system requests exit
	 * (HOME button, sleep, or system timeout). appletLockExit() should
	 * prevent this during test runs, but HOME can still trigger it.
	 * Return true unconditionally to avoid aborting long test runs. */
	appletMainLoop();
	return true;
}

void Platform::getMemoryLimits(tcu::PlatformMemoryLimits& limits) const
{
	// Nintendo Switch has 4GB RAM, ~3.2GB available to apps
	limits.totalSystemMemory					= 512 * 1024 * 1024;
	limits.totalDeviceLocalMemory				= 0;	// Unified memory
	limits.deviceMemoryAllocationGranularity	= 4096;
	limits.devicePageSize						= 4096;
	limits.devicePageTableEntrySize				= 8;
	limits.devicePageTableHierarchyLevels		= 3;
}

} // namespace nx
} // namespace tcu

// --- Entry Point ---
// Called by tcuMain.cpp to create the platform instance.

tcu::Platform* createPlatform(void)
{
	return new tcu::nx::Platform();
}
