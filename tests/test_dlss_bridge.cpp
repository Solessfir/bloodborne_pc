// SPDX-License-Identifier: GPL-2.0-or-later
// Standalone Linux NGX smoke test. Requires the bridge and NVIDIA's native DLSS runtime.
#include "gpu/dlss_bridge/bbport_dlss_bridge.h"

#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>
#include <unistd.h>

namespace {
void Require(bool condition, const char* operation) {
    if (!condition)
        throw std::runtime_error(operation);
}

void Check(VkResult result, const char* operation) {
    if (result != VK_SUCCESS)
        throw std::runtime_error(std::string(operation) + ": VkResult " + std::to_string(result));
}

void Log(int warning, const char* message) {
    std::fprintf(stderr, "DLSS%s: %s\n", warning ? " warning" : "", message);
}

struct Image {
    BbDlssImage resource{};
    VkDeviceMemory memory{};
};

struct Smoke {
    void* library{};
    const BbDlssApi* api{};
    VkInstance instance{};
    VkPhysicalDevice physical{};
    VkDevice device{};
    VkQueue queue{};
    VkCommandPool pool{};
    VkCommandBuffer command{};
    VkPhysicalDeviceMemoryProperties memory_properties{};
    std::array<Image, 4> images{};
    VkBuffer readback{};
    VkDeviceMemory readback_memory{};
    void* mapped{};
    std::filesystem::path data_directory;

    ~Smoke() {
        if (device)
            vkDeviceWaitIdle(device);
        if (api)
            api->Shutdown();
        if (device) {
            if (mapped)
                vkUnmapMemory(device, readback_memory);
            if (readback)
                vkDestroyBuffer(device, readback, nullptr);
            if (readback_memory)
                vkFreeMemory(device, readback_memory, nullptr);
            for (auto& image : images) {
                if (image.resource.view)
                    vkDestroyImageView(device, image.resource.view, nullptr);
                if (image.resource.image)
                    vkDestroyImage(device, image.resource.image, nullptr);
                if (image.memory)
                    vkFreeMemory(device, image.memory, nullptr);
            }
            if (pool)
                vkDestroyCommandPool(device, pool, nullptr);
            vkDestroyDevice(device, nullptr);
        }
        if (instance)
            vkDestroyInstance(instance, nullptr);
        if (library)
            dlclose(library);
        if (!data_directory.empty()) {
            std::error_code error;
            std::filesystem::remove_all(data_directory, error);
        }
    }

    uint32_t MemoryType(uint32_t bits, VkMemoryPropertyFlags flags) const {
        for (uint32_t i = 0; i < memory_properties.memoryTypeCount; ++i)
            if ((bits & (1u << i)) &&
                (memory_properties.memoryTypes[i].propertyFlags & flags) == flags)
                return i;
        throw std::runtime_error("No suitable Vulkan memory type");
    }

    void Initialize(const std::filesystem::path& directory) {
        const auto path = directory / "libbbport_dlss.so";
        library = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
        if (!library)
            throw std::runtime_error(dlerror());
        const auto get_api = reinterpret_cast<BbDlssGetApiFn>(dlsym(library, "BbDlssGetApi"));
        Require(get_api != nullptr, "Bridge has no BbDlssGetApi export");
        const auto* loaded_api = get_api();
        Require(loaded_api && loaded_api->abi == BBPORT_DLSS_BRIDGE_ABI,
                "Bridge ABI does not match the smoke test");
        api = loaded_api;
        char temporary[] = "/tmp/bbport-dlss-smoke-XXXXXX";
        Require(mkdtemp(temporary) != nullptr, "Cannot create NGX data directory");
        data_directory = temporary;
        Require(api->Configure(directory.wstring().c_str(), data_directory.wstring().c_str(), Log),
                "Bridge Configure failed");
        uint32_t count{};
        const VkExtensionProperties* required{};
        Require(api->InstanceExtensions(&count, &required), "InstanceExtensions failed");
        std::vector<const char*> extensions;
        for (uint32_t i = 0; i < count; ++i) {
            std::printf("Instance extension: %s\n", required[i].extensionName);
            extensions.push_back(required[i].extensionName);
        }
        const VkApplicationInfo application{.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
            .pApplicationName = "bbport DLSS smoke", .apiVersion = VK_API_VERSION_1_3};
        const VkInstanceCreateInfo instance_info{.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
            .pApplicationInfo = &application,
            .enabledExtensionCount = static_cast<uint32_t>(extensions.size()),
            .ppEnabledExtensionNames = extensions.data()};
        Check(vkCreateInstance(&instance_info, nullptr, &instance), "vkCreateInstance");
        Check(vkEnumeratePhysicalDevices(instance, &count, nullptr), "Enumerate device count");
        std::vector<VkPhysicalDevice> devices(count);
        Check(vkEnumeratePhysicalDevices(instance, &count, devices.data()), "Enumerate devices");
        for (const auto candidate : devices) {
            VkPhysicalDeviceProperties properties{};
            vkGetPhysicalDeviceProperties(candidate, &properties);
            if (properties.vendorID == 0x10de) {
                physical = candidate;
                std::printf("GPU: %s\n", properties.deviceName);
                break;
            }
        }
        Require(physical != VK_NULL_HANDLE, "No NVIDIA Vulkan device found");
        Require(api->DeviceExtensions(instance, physical, &count, &required),
                "DeviceExtensions failed");
        extensions.clear();
        for (uint32_t i = 0; i < count; ++i) {
            std::printf("Device extension: %s\n", required[i].extensionName);
            extensions.push_back(required[i].extensionName);
        }
        uint32_t family_count{};
        vkGetPhysicalDeviceQueueFamilyProperties(physical, &family_count, nullptr);
        std::vector<VkQueueFamilyProperties> families(family_count);
        vkGetPhysicalDeviceQueueFamilyProperties(physical, &family_count, families.data());
        uint32_t family = family_count;
        for (uint32_t i = 0; i < family_count; ++i)
            if ((families[i].queueFlags & (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) ==
                (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) {
                family = i;
                break;
            }
        Require(family != family_count, "No graphics and compute queue found");
        VkPhysicalDeviceVulkan13Features features13{
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
        VkPhysicalDeviceVulkan12Features features12{
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES, .pNext = &features13};
        VkPhysicalDeviceVulkan11Features features11{
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES, .pNext = &features12};
        VkPhysicalDeviceFeatures2 features{
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &features11};
        vkGetPhysicalDeviceFeatures2(physical, &features);
        const float priority = 1.0f;
        const VkDeviceQueueCreateInfo queue_info{.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
        const VkDeviceCreateInfo device_info{.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            .pNext = &features, .queueCreateInfoCount = 1, .pQueueCreateInfos = &queue_info,
            .enabledExtensionCount = static_cast<uint32_t>(extensions.size()),
            .ppEnabledExtensionNames = extensions.data()};
        Check(vkCreateDevice(physical, &device_info, nullptr, &device), "vkCreateDevice");
        vkGetDeviceQueue(device, family, 0, &queue);
        vkGetPhysicalDeviceMemoryProperties(physical, &memory_properties);
        Require(api->Initialize(instance, physical, device, vkGetInstanceProcAddr, vkGetDeviceProcAddr),
                "NGX Initialize failed");
        Require(api->FrameGenMaxCount() == 0, "Linux bridge unexpectedly advertises Frame Generation");
        const VkCommandPoolCreateInfo pool_info{.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = family};
        Check(vkCreateCommandPool(device, &pool_info, nullptr, &pool), "vkCreateCommandPool");
        const VkCommandBufferAllocateInfo allocate{
            .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = pool,
            .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
        Check(vkAllocateCommandBuffers(device, &allocate, &command), "vkAllocateCommandBuffers");
    }

    void CreateImage(Image& image, uint32_t width, uint32_t height, VkFormat format,
                     VkImageAspectFlags aspect) {
        image.resource = {.range = {aspect, 0, 1, 0, 1}, .format = format,
                          .width = width, .height = height};
        const VkImageUsageFlags usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT |
            (aspect == VK_IMAGE_ASPECT_DEPTH_BIT ? VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT :
                VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
        const VkImageCreateInfo info{.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
            .imageType = VK_IMAGE_TYPE_2D, .format = format, .extent = {width, height, 1},
            .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
            .tiling = VK_IMAGE_TILING_OPTIMAL,
            .usage = usage,
            .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
        Check(vkCreateImage(device, &info, nullptr, &image.resource.image), "vkCreateImage");
        VkMemoryRequirements requirements{};
        vkGetImageMemoryRequirements(device, image.resource.image, &requirements);
        const VkMemoryAllocateInfo allocate{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = requirements.size,
            .memoryTypeIndex = MemoryType(requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
        Check(vkAllocateMemory(device, &allocate, nullptr, &image.memory), "Allocate image memory");
        Check(vkBindImageMemory(device, image.resource.image, image.memory, 0), "Bind image memory");
        const VkImageViewCreateInfo view{.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
            .image = image.resource.image, .viewType = VK_IMAGE_VIEW_TYPE_2D,
            .format = format, .subresourceRange = image.resource.range};
        Check(vkCreateImageView(device, &view, nullptr, &image.resource.view), "vkCreateImageView");
    }

    void Begin() {
        Check(vkResetCommandBuffer(command, 0), "vkResetCommandBuffer");
        const VkCommandBufferBeginInfo begin{.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
        Check(vkBeginCommandBuffer(command, &begin), "vkBeginCommandBuffer");
    }

    void Submit() {
        Check(vkEndCommandBuffer(command), "vkEndCommandBuffer");
        const VkSubmitInfo submit{.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
            .commandBufferCount = 1, .pCommandBuffers = &command};
        Check(vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE), "vkQueueSubmit");
        Check(vkQueueWaitIdle(queue), "vkQueueWaitIdle");
    }

    void Run(int quality) {
        constexpr uint32_t output_width = 960, output_height = 540;
        const uint32_t width = quality == 0 ? output_width : 640;
        const uint32_t height = quality == 0 ? output_height : 360;
        CreateImage(images[0], width, height, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_ASPECT_COLOR_BIT);
        CreateImage(images[1], width, height, VK_FORMAT_D32_SFLOAT, VK_IMAGE_ASPECT_DEPTH_BIT);
        CreateImage(images[2], width, height, VK_FORMAT_R16G16_SFLOAT, VK_IMAGE_ASPECT_COLOR_BIT);
        CreateImage(images[3], output_width, output_height, VK_FORMAT_R16G16B16A16_SFLOAT,
                    VK_IMAGE_ASPECT_COLOR_BIT);
        Begin();
        for (const auto& image : images) {
            const VkImageMemoryBarrier barrier{.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED,
                .newLayout = VK_IMAGE_LAYOUT_GENERAL, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = image.resource.image,
                .subresourceRange = image.resource.range};
            vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
            if (image.resource.range.aspectMask == VK_IMAGE_ASPECT_DEPTH_BIT) {
                const VkClearDepthStencilValue depth{0.5f, 0};
                vkCmdClearDepthStencilImage(command, image.resource.image, VK_IMAGE_LAYOUT_GENERAL,
                    &depth, 1, &image.resource.range);
            } else {
                const VkClearColorValue color = &image == &images[0] ?
                    VkClearColorValue{{0.25f, 0.5f, 0.75f, 1.0f}} : VkClearColorValue{};
                vkCmdClearColorImage(command, image.resource.image, VK_IMAGE_LAYOUT_GENERAL,
                    &color, 1, &image.resource.range);
            }
        }
        const VkMemoryBarrier ready{.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT};
        vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT,
            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &ready, 0, nullptr, 0, nullptr);
        const BbDlssFeature feature{width, height, output_width, output_height, quality, 0, 0, 0};
        Require(api->CreateFeature(command, &feature), "DLSS CreateFeature failed");
        Submit();
        for (int frame = 0; frame < 3; ++frame) {
            Begin();
            const VkMemoryBarrier reuse{.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT,
                .dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT};
            vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &reuse, 0, nullptr, 0, nullptr);
            const BbDlssEvaluate evaluate{images[0].resource, images[1].resource, images[2].resource,
                images[3].resource, 0.0f, 0.0f, frame == 0, 16.667f, 0.0f};
            Require(api->Evaluate(command, &evaluate), "DLSS Evaluate failed");
            Submit();
        }
        const VkDeviceSize bytes = output_width * output_height * 8;
        const VkBufferCreateInfo buffer_info{.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = bytes, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
        Check(vkCreateBuffer(device, &buffer_info, nullptr, &readback), "Create readback buffer");
        VkMemoryRequirements requirements{};
        vkGetBufferMemoryRequirements(device, readback, &requirements);
        const VkMemoryAllocateInfo allocate{.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = requirements.size,
            .memoryTypeIndex = MemoryType(requirements.memoryTypeBits,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
        Check(vkAllocateMemory(device, &allocate, nullptr, &readback_memory), "Allocate readback memory");
        Check(vkBindBufferMemory(device, readback, readback_memory, 0), "Bind readback memory");
        Begin();
        const VkImageMemoryBarrier copy{.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
            .oldLayout = VK_IMAGE_LAYOUT_GENERAL, .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = images[3].resource.image,
            .subresourceRange = images[3].resource.range};
        vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &copy);
        const VkBufferImageCopy region{.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .imageExtent = {output_width, output_height, 1}};
        vkCmdCopyImageToBuffer(command, images[3].resource.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                              readback, 1, &region);
        const VkMemoryBarrier host{.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
            0, 1, &host, 0, nullptr, 0, nullptr);
        Submit();
        Check(vkMapMemory(device, readback_memory, 0, bytes, 0, &mapped), "Map DLSS output");
        const auto* pixels = static_cast<const uint16_t*>(mapped);
        for (uint32_t y = output_height / 4; y < output_height * 3 / 4; ++y)
            for (uint32_t x = output_width / 4; x < output_width * 3 / 4; ++x)
                for (uint32_t channel = 0; channel < 3; ++channel) {
                    const auto half = pixels[(y * output_width + x) * 4 + channel];
                    const auto exponent = (half >> 10) & 31;
                    Require(!(half & 0x8000) && exponent > 0 && exponent < 31,
                            "DLSS output has zero, negative or non-finite central pixels");
                    const float value = std::ldexp(1.0f + (half & 1023) / 1024.0f,
                                                  static_cast<int>(exponent) - 15);
                    Require(std::abs(value - (channel + 1) * 0.25f) < 0.1f,
                            "DLSS output does not preserve the synthetic input color");
                }
        std::printf("PASS: %s, three evaluated frames, output readback verified\n",
                    quality == 0 ? "DLAA" : "Quality");
        vkUnmapMemory(device, readback_memory);
        mapped = nullptr;
        vkDestroyBuffer(device, readback, nullptr);
        readback = VK_NULL_HANDLE;
        vkFreeMemory(device, readback_memory, nullptr);
        readback_memory = VK_NULL_HANDLE;
        api->ReleaseFeature();
        for (auto& image : images) {
            vkDestroyImageView(device, image.resource.view, nullptr);
            vkDestroyImage(device, image.resource.image, nullptr);
            vkFreeMemory(device, image.memory, nullptr);
            image = {};
        }
    }
};
} // namespace

int main(int argc, char** argv) {
    try {
        Require(argc <= 2, "Usage: test_dlss_bridge [bridge-and-runtime-directory]");
        Smoke smoke;
        smoke.Initialize(std::filesystem::absolute(argc == 2 ? argv[1] : "out"));
        smoke.Run(0);
        smoke.Run(1);
        std::puts("PASS: Linux FrameGenMaxCount is zero");
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "FAIL: %s\n", error.what());
        return 1;
    }
}
